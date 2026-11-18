import json
import os
import stat
import sys
from datetime import datetime

import pytest

from src import forecast as fc
from src import runtime
from src.venue import Market

NOW = 1_800_000_000.0


def market(**kw):
    base = dict(market_id="cpi-above-3", question="Will CPI inflation be above 3.0%?", rules="Resolves per bls.gov.",
                event_title="January CPI", category="economics", end_ts=NOW + 20 * 86400, outcome="Yes")
    return Market(**{**base, **kw})


def answer(p=0.6, **kw):
    base = {"resolution_summary": "YES if BLS prints above 3.0%", "rules_clear": True, "base_rate": "about 40%",
            "key_facts": ["Dec CPI 2.9% (bls.gov, 2027-01-13)"], "case_for_yes": "energy", "case_for_no": "shelter",
            "p_yes": p, "confidence": "medium", "caveats": ["could not open one page"], "flags": [], "sources": ["https://www.bls.gov/cpi/"]}
    return {**base, **kw}


def test_prompt_carries_date_question_rules_and_no_price():
    text = fc.build_prompt(market(), NOW)
    assert "Today is Friday 2027-01-15" in text
    assert "Will CPI inflation be above 3.0%?" in text and "<rules>" in text and "bls.gov" in text
    assert "Market closes: 2027-02-04" in text
    for word in ("price", "bid", "ask", "cents", "odds"):
        assert word not in text.lower()
    assert "(none provided)" in fc.build_prompt(market(rules=""), NOW)


def test_system_prompt_states_the_untrusted_content_rule():
    assert "never instructions" in fc.SYSTEM and "trading price" in fc.SYSTEM
    assert "caveats" in fc.SCHEMA["required"]            # ordinary doubts have a place that does not block a trade
    assert set(fc.SCHEMA["required"]) == set(fc.SCHEMA["properties"])
    assert "description" not in json.dumps(fc.compact_schema())
    assert "rules_clear" in fc.field_guide()


@pytest.mark.parametrize("bad", [
    {"p_yes": 1.3}, {"p_yes": "0.6"}, {"p_yes": True}, {"p_yes": float("nan")},
    {"confidence": "certain"}, {"rules_clear": "yes"}, {"flags": "none"},
])
def test_validate_rejects_malformed_answers(bad):
    with pytest.raises(ValueError):
        fc.validate(answer(**bad))
    fc.validate(answer())
    with pytest.raises(ValueError):
        fc.validate({k: v for k, v in answer().items() if k != "sources"})
    with pytest.raises(ValueError):
        fc.validate("0.6")


def test_aggregate_takes_the_median_and_the_most_cautious_view():
    f = fc.aggregate("m", [answer(0.55), answer(0.60, confidence="high"), answer(0.68, rules_clear=False, flags=["thin sourcing"])],
                     "test", "model", cost_usd=0.5, now=NOW)
    assert f.p_yes == 0.60 and f.p_runs == [0.55, 0.60, 0.68]
    assert f.confidence == "medium" and f.rules_clear is False and f.flags == ["thin sourcing"]
    assert f.cost_usd == 0.5 and f.ts == NOW and "Base rate" in f.rationale and "Caveats: could not open" in f.rationale


def test_runs_that_disagree_are_downgraded():
    f = fc.aggregate("m", [answer(0.30), answer(0.60), answer(0.65)], "t", "m")
    assert f.confidence == "low" and any("disagree" in x for x in f.flags)


def test_aggregate_needs_two_good_runs_and_clamps_extremes():
    assert fc.aggregate("m", [answer(0.6), {"p_yes": 2}], "t", "m") is None
    assert fc.aggregate("m", [], "t", "m") is None
    f = fc.aggregate("m", [answer(1.0), answer(0.99)], "t", "m")
    assert f.p_yes == fc.P_CEIL


def test_file_backend_writes_a_request_then_reads_the_answer(tmp_path):
    be = fc.FileBackend(tmp_path)
    m = market()
    assert be.forecast(m, NOW) is None
    req = json.loads((tmp_path / "requests" / "cpi-above-3.json").read_text())
    assert req["prompt"].startswith("Today is") and req["schema"]["required"]
    (tmp_path / "forecasts" / "cpi-above-3.json").write_text(json.dumps(answer(0.62)))
    os.utime(tmp_path / "forecasts" / "cpi-above-3.json", (NOW, NOW))
    f = be.forecast(m, NOW + 60)
    assert f.p_yes == 0.62 and f.backend == "file"
    assert be.forecast(m, NOW + 120) is None                       # an answer is used once


def test_file_backend_ignores_a_stale_answer(tmp_path):
    be = fc.FileBackend(tmp_path, max_age_hours=6)
    path = tmp_path / "forecasts" / "cpi-above-3.json"
    path.write_text(json.dumps(answer(0.62)))
    os.utime(path, (NOW, NOW))
    assert be.forecast(market(), NOW + 7 * 3600) is None


def fake_claude(tmp_path, body: str):
    """A stand-in `claude` executable: a Python script that reads stdin and prints what the CLI would."""
    script = tmp_path / "fake_claude.py"
    script.write_text("import sys, json\nargs = sys.argv[1:]\nprompt = sys.stdin.read()\n" + body)
    if sys.platform == "win32":
        exe = tmp_path / "claude.cmd"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        exe = tmp_path / "claude"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


def test_claude_code_backend_parses_structured_output(tmp_path):
    body = ("ans = " + repr(answer(0.64)) + "\n"
            "assert '--tools' in args and args[args.index('--tools') + 1] == 'WebSearch,WebFetch'\n"
            "assert '--no-session-persistence' in args and '--strict-mcp-config' in args\n"
            "assert 'Today is' in prompt\n"
            "print(json.dumps({'is_error': False, 'total_cost_usd': 0.1, 'structured_output': ans, 'result': '',\n"
            "                  'modelUsage': {'claude-test-1': {}}}))\n")
    be = fc.ClaudeCodeBackend(runs=3, cwd=tmp_path / "cwd", executable=fake_claude(tmp_path, body), timeout_s=60)
    f = be.forecast(market(), NOW)
    assert f.p_yes == 0.64 and f.p_runs == [0.64] * 3 and f.cost_usd == pytest.approx(0.3)
    assert f.model == "claude-test-1"                             # the model that answered, not the alias asked for
    assert "--model" in be.command()
    assert "--model" not in fc.ClaudeCodeBackend(model=None, cwd=tmp_path / "cwd2").command()
    assert (tmp_path / "cwd" / "forecaster_system_prompt.txt").read_text().startswith("You are a careful forecaster")


def test_claude_code_backend_falls_back_to_result_text_and_survives_errors(tmp_path):
    ok = "print(json.dumps({'is_error': False, 'result': json.dumps(" + repr(answer(0.4)) + ")}))\n"
    be = fc.ClaudeCodeBackend(runs=2, cwd=tmp_path / "a", executable=fake_claude(tmp_path, ok), timeout_s=60)
    assert be.forecast(market(), NOW).p_yes == 0.4
    for body in ("print(json.dumps({'is_error': True, 'result': 'rate limited'}))\n", "print('not json')\n", "sys.exit(2)\n"):
        be = fc.ClaudeCodeBackend(runs=2, cwd=tmp_path / "b", executable=fake_claude(tmp_path, body), timeout_s=60)
        assert be.forecast(market(), NOW) is None
    missing = fc.ClaudeCodeBackend(runs=1, cwd=tmp_path / "c", executable=str(tmp_path / "nope"))
    assert missing.forecast(market(), NOW) is None


def test_single_run_mode_still_forecasts_and_failures_say_why(tmp_path):
    ok = "print(json.dumps({'is_error': False, 'structured_output': " + repr(answer(0.4)) + "}))\n"
    be = fc.ClaudeCodeBackend(runs=1, cwd=tmp_path / "a", executable=fake_claude(tmp_path, ok), timeout_s=60)
    assert be.forecast(market(), NOW).p_yes == 0.4
    bad = "sys.stderr.write('Not logged in\\n'); sys.exit(1)\n"
    be = fc.ClaudeCodeBackend(runs=1, cwd=tmp_path / "b", executable=fake_claude(tmp_path, bad), timeout_s=60)
    assert be.forecast(market(), NOW) is None and "Not logged in" in be.last_error
    gone = fc.ClaudeCodeBackend(runs=1, cwd=tmp_path / "c", executable=str(tmp_path / "nope"))
    assert gone.forecast(market(), NOW) is None and "could not start" in gone.last_error


def test_a_hung_claude_is_killed_at_the_timeout(tmp_path):
    hang = "import time\ntime.sleep(60)\n"
    be = fc.ClaudeCodeBackend(runs=1, cwd=tmp_path / "h", executable=fake_claude(tmp_path, hang), timeout_s=2)
    import time as _t
    t0 = _t.time()
    assert be.forecast(market(), NOW) is None and "timed out" in be.last_error
    assert _t.time() - t0 < 20


def test_make_backend(tmp_path, monkeypatch):
    assert isinstance(fc.make_backend({}, tmp_path), fc.ClaudeCodeBackend)
    assert isinstance(fc.make_backend({"forecaster": {"backend": "file"}}, tmp_path), fc.FileBackend)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        fc.make_backend({"forecaster": {"backend": "api"}}, tmp_path)
    with pytest.raises(ValueError):
        fc.make_backend({"forecaster": {"backend": "gpt"}}, tmp_path)


# ---- runtime ---------------------------------------------------------------------

def test_quiet_windows():
    at = lambda h, m: datetime(2026, 11, 18, h, m)
    assert runtime.in_quiet_window(["17:15-18:20"], at(17, 30)) == "17:15-18:20"
    assert runtime.in_quiet_window(["17:15-18:20"], at(18, 20)) is None
    assert runtime.in_quiet_window(["23:00-02:00"], at(1, 0)) == "23:00-02:00"
    assert runtime.in_quiet_window(["23:00-02:00"], at(12, 0)) is None
    assert runtime.in_quiet_window(["9:00-10:00"], at(9, 30)) == "9:00-10:00"       # no leading zero needed
    with pytest.raises(ValueError):                                              # a typo is an error, not "no window"
        runtime.in_quiet_window(["nonsense"], at(12, 0))
    assert runtime.in_quiet_window(None, at(12, 0)) is None


def test_lock_blocks_a_second_cycle_and_releases(tmp_path):
    path = tmp_path / "data" / "cycle.lock"
    with runtime.Lock(path):
        with pytest.raises(runtime.Busy):
            with runtime.Lock(path):
                pass
    assert not path.exists()
    with runtime.Lock(path):
        pass


def test_lock_heartbeat_and_takeover_do_not_fight(tmp_path):
    path = tmp_path / "cycle.lock"
    first = runtime.Lock(path, stale_hours=1)
    first.__enter__()
    old = path.stat().st_mtime - 2 * 3600
    os.utime(path, (old, old))
    first.touch()                                    # the running cycle shows it is alive
    with pytest.raises(runtime.Busy):
        runtime.Lock(path, stale_hours=1).__enter__()
    os.utime(path, (old, old))                       # now it really is dead: a second run takes over
    second = runtime.Lock(path, stale_hours=1)
    second.__enter__()
    first.__exit__(None, None, None)                 # the first run waking up must not delete the second's lock
    assert path.exists() and second.ours()
    second.__exit__(None, None, None)
    assert not path.exists()


def test_stale_lock_is_taken_over(tmp_path):
    path = tmp_path / "cycle.lock"
    path.write_text("pid 1")
    old = path.stat().st_mtime - 4 * 3600
    os.utime(path, (old, old))
    with runtime.Lock(path, stale_hours=3):
        assert "pid" in path.read_text()


def test_preflight(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "lower_priority", lambda: None)
    monkeypatch.setattr(runtime, "free_memory_gb", lambda: 0.5)
    with pytest.raises(runtime.Busy, match="memory"):
        runtime.preflight({"runtime": {"min_free_gb": 1.5}}, tmp_path)
    monkeypatch.setattr(runtime, "free_memory_gb", lambda: None)
    runtime.preflight({"runtime": {"min_free_gb": 1.5}}, tmp_path)       # unknown memory is not a reason to stop
    monkeypatch.setattr(runtime, "in_quiet_window", lambda w, now=None: "17:15-18:20")
    with pytest.raises(runtime.Busy, match="quiet"):
        runtime.preflight({"runtime": {"quiet_windows": ["17:15-18:20"]}}, tmp_path)
    assert isinstance(runtime.free_memory_gb.__call__(), type(None))
