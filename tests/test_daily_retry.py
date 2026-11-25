import json
import sys
import time
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import open_fallback  # noqa: E402
import run_daily_retry as sup  # noqa: E402
from src import daily_retry as dr  # noqa: E402

POL = dr.Policy(every_min=30, max_attempts=6, last_start=dtime(22, 0), attempt_timeout_min=90)
T0 = datetime(2026, 11, 19, 17, 30)


def test_decide_by_exit_code_attempts_and_clock():
    nxt = T0 + timedelta(minutes=31)
    assert dr.decide(0, 1, T0, nxt, POL) == "done"
    assert dr.decide(4, 1, T0, nxt, POL) == "safety_stop"        # never retried
    assert dr.decide(3, 1, T0, nxt, POL) == "retry"              # memory guard / data not current
    assert dr.decide(1, 1, T0, nxt, POL) == "retry"              # crash
    assert dr.decide(None, 1, T0, nxt, POL) == "retry"           # time limit
    assert dr.decide(3, 6, T0, nxt, POL) == "give_up"            # max attempts reached
    assert dr.decide(3, 2, T0, datetime(2026, 11, 19, 22, 1), POL) == "give_up"   # after last_start
    assert dr.decide(3, 2, T0, datetime(2026, 11, 20, 0, 10), POL) == "give_up"   # next local day


def test_policy_from_config_defaults_and_overrides():
    assert dr.policy_from_config(None) == dr.Policy()
    p = dr.policy_from_config({"retry": {"every_min": 15, "max_attempts": 3, "last_start": "21:30"}})
    assert (p.every_min, p.max_attempts, p.last_start, p.attempt_timeout_min) == (15, 3, dtime(21, 30), 90)


def test_reason_prefers_memory_guard_then_error_log_then_exit_code():
    mg = ("Universe trim: ...\n\nMEMORY GUARD: only 1.00 GB of RAM free (floor 1.0 GB). Stopping the daily job "
          "before the machine freezes. No orders were sent by this run.\n")
    assert dr.reason(3, mg, []) == "MEMORY GUARD: only 1.00 GB of RAM free (floor 1.0 GB) (memory guard)"
    err = ["2026-11-19 17:31:02 no trading: last bar 2026-11-18, expected 2026-11-19"]
    assert dr.reason(3, "ERROR: no trading", err) == "no trading: last bar 2026-11-18, expected 2026-11-19"
    assert "time limit" in dr.reason(None, "", [])
    assert dr.reason(1, "Traceback ...\nKeyError: 'x'\n", []) == "exit code 1: KeyError: 'x'"


def _patch_files(monkeypatch, tmp_path):
    monkeypatch.setattr(sup, "LOG", tmp_path / "run_daily.log")
    monkeypatch.setattr(sup, "ERRORS", tmp_path / "run_daily_errors.log")
    monkeypatch.setattr(sup, "ORDERS", tmp_path / "orders.log")


class Clock:
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += timedelta(seconds=s)


def _runner(codes, clock, tmp_path, on_run=None):
    """Fake run_daily: each call takes 2 minutes and returns the next exit code; `on_run(i)` can write logs."""
    calls = []

    def run(extra, timeout_min):
        i = len(calls)
        calls.append(extra)
        if on_run:
            on_run(i)
        clock.t += timedelta(minutes=2)
        return codes[i]
    return run, calls


def test_memory_guard_then_recovery_posts_two_alerts(monkeypatch, tmp_path):
    _patch_files(monkeypatch, tmp_path)
    clock, posted = Clock(T0), []

    def on_run(i):
        if i == 0:
            (tmp_path / "run_daily.log").write_text("MEMORY GUARD: only 0.90 GB of RAM free (floor 1.0 GB). Stopping x\n")
        else:
            (tmp_path / "orders.log").write_text(json.dumps({"date": "2026-11-19", "orders": [{}] * 66}) + "\n")
    run, calls = _runner([3, 0], clock, tmp_path, on_run)
    code = sup.supervise(["--force"], POL, run=run, now=clock.now, sleep=clock.sleep, notify=posted.append)
    assert code == 0 and len(calls) == 2 and calls[0] == ["--force"]
    assert len(posted) == 2
    assert "stopped" in posted[0] and "0.90 GB" in posted[0] and "6:02 PM CT" in posted[0]   # retry 30 min after 5:32
    assert "recovered" in posted[1] and "66 orders" in posted[1]


def test_normal_day_posts_nothing(monkeypatch, tmp_path):
    _patch_files(monkeypatch, tmp_path)
    clock, posted = Clock(T0), []
    run, calls = _runner([0], clock, tmp_path)
    assert sup.supervise([], POL, run=run, now=clock.now, sleep=clock.sleep, notify=posted.append) == 0
    assert posted == [] and len(calls) == 1


def test_safety_stop_is_not_retried(monkeypatch, tmp_path):
    _patch_files(monkeypatch, tmp_path)
    clock, posted = Clock(T0), []

    def on_run(i):
        (tmp_path / "run_daily_errors.log").write_text("2026-11-19 17:45:00 no trading (safety limit): kill switch\n")
    run, calls = _runner([4], clock, tmp_path, on_run)
    assert sup.supervise([], POL, run=run, now=clock.now, sleep=clock.sleep, notify=posted.append) == 4
    assert len(calls) == 1 and len(posted) == 1 and "safety stop" in posted[0] and "kill switch" in posted[0]


def test_gives_up_after_max_attempts_with_one_warning_and_one_final_alert(monkeypatch, tmp_path):
    _patch_files(monkeypatch, tmp_path)
    clock, posted = Clock(T0), []
    run, calls = _runner([3] * 10, clock, tmp_path)
    assert sup.supervise([], POL, run=run, now=clock.now, sleep=clock.sleep, notify=posted.append) == 3
    assert len(calls) == POL.max_attempts
    assert len(posted) == 2 and "stopped" in posted[0] and "gave up" in posted[1] and "No orders" in posted[1]
    assert clock.t.time() < dtime(22, 0)


def test_late_start_gives_up_instead_of_running_past_last_start(monkeypatch, tmp_path):
    _patch_files(monkeypatch, tmp_path)
    clock, posted = Clock(datetime(2026, 11, 19, 21, 45)), []
    run, calls = _runner([1, 0], clock, tmp_path)
    assert sup.supervise([], POL, run=run, now=clock.now, sleep=clock.sleep, notify=posted.append) == 1
    assert len(calls) == 1 and len(posted) == 1 and "gave up" in posted[0]


def test_finished_run_that_logged_errors_is_reported(monkeypatch, tmp_path):
    _patch_files(monkeypatch, tmp_path)
    clock, posted = Clock(T0), []

    def on_run(i):
        (tmp_path / "run_daily_errors.log").write_text("2026-11-19 18:02:00 2 order(s) rejected on 2026-11-19: AYI, KNX\n")
    run, _ = _runner([0], clock, tmp_path, on_run)
    assert sup.supervise([], POL, run=run, now=clock.now, sleep=clock.sleep, notify=posted.append) == 0
    assert len(posted) == 1 and "AYI, KNX" in posted[0] and "2026-11-19 18:02:00" not in posted[0]


def test_fallback_lock_allows_one_sender_and_takes_over_a_stale_lock(tmp_path, monkeypatch):
    lock = tmp_path / "fallback" / ".lock"
    monkeypatch.setattr(open_fallback, "_held_lock", False)
    assert open_fallback.take_lock(lock) is True
    monkeypatch.setattr(open_fallback, "_held_lock", False)       # a second process holds nothing yet
    assert open_fallback.take_lock(lock) is False
    old = time.time() - 3600
    import os
    os.utime(lock, (old, old))
    assert open_fallback.take_lock(lock, stale_s=600) is True       # left by a killed run
    open_fallback.release_lock(lock)
    assert not lock.exists()


def test_tracker_runs_once_after_a_finished_run_only(monkeypatch, tmp_path):
    _patch_files(monkeypatch, tmp_path)
    for codes, expected_calls in (([0], 1), ([3, 0], 1), ([4], 0), ([3] * 10, 0)):
        clock, tracked = Clock(T0), []
        run, _ = _runner(codes, clock, tmp_path)
        sup.supervise([], POL, run=run, now=clock.now, sleep=clock.sleep, notify=lambda t: None,
                      track=lambda: tracked.append(1))
        assert len(tracked) == expected_calls, codes


def test_tracker_error_never_changes_the_exit_code(monkeypatch, tmp_path):
    _patch_files(monkeypatch, tmp_path)
    clock, posted = Clock(T0), []
    run, _ = _runner([0], clock, tmp_path)

    def boom():
        raise OSError("cannot start")
    assert sup.supervise([], POL, run=run, now=clock.now, sleep=clock.sleep, notify=posted.append, track=boom) == 0
    assert posted == []


class _FakeProc:
    def __init__(self, code=None, hang=False):
        self.code, self.hang, self.killed = code, hang, False

    def wait(self, timeout=None):
        if self.hang and not self.killed:
            raise sup.subprocess.TimeoutExpired("track_live.py", timeout)
        return self.code

    def kill(self):
        self.killed = True


def test_run_tracker_logs_a_failure_or_timeout_but_not_a_success(monkeypatch, tmp_path):
    _patch_files(monkeypatch, tmp_path)
    errors = tmp_path / "run_daily_errors.log"
    for proc, code, logged in ((_FakeProc(0), 0, None), (_FakeProc(1), 1, "exit code 1"),
                               (_FakeProc(hang=True), None, "did not finish within 10 min")):
        errors.write_text("")
        seen = {}

        def popen(args, cwd=None, _p=proc):
            seen["args"] = args
            return _p
        monkeypatch.setattr(sup.subprocess, "Popen", popen)
        assert sup.run_tracker() == code
        assert seen["args"][-1].endswith("track_live.py")
        text = errors.read_text()
        if logged is None:
            assert text == ""
        else:
            assert "live-vs-model tracker failed" in text and logged in text
    assert proc.killed
