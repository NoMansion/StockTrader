"""Supervisor for the scheduled daily job (Task Scheduler "StockTrader Daily", weekdays 5:30 pm CT):

    python scripts/run_daily_retry.py >> data/run_daily.log 2>&1   # what the task runs
    python scripts/run_daily_retry.py --test-alert                 # post one test message to Discord, run nothing

Runs scripts/run_daily.py. When it stops without finishing (memory guard, price data not current yet, a crash) it
waits and runs it again. It posts to the Discord report channel on the first stop (with the retry time), on
recovery, when it gives up, on a safety stop (never retried), and when a run finishes but wrote new lines to
data/run_daily_errors.log (rejected orders, for example). A normal day posts nothing.
Retry policy and exit codes: src/daily_retry.py; settings: live.retry in config.yaml. Any other arguments are
passed through to run_daily.py.
"""
import _bootstrap  # noqa: F401

import argparse
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from src import daily_retry as dr
from src.notify import post_text

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "run_daily.log"
ERRORS = ROOT / "data" / "run_daily_errors.log"
ORDERS = ROOT / "data" / "orders.log"


def say(msg: str) -> None:
    print(f"[retry {datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def size(p: Path) -> int:
    return p.stat().st_size if p.exists() else 0


def read_from(p: Path, offset: int) -> str:
    """What was appended to a log since `offset` ("" if unreadable)."""
    try:
        with open(p, "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def todays_batch_size(day: date) -> int | None:
    """Order count of the last run_daily batch in orders.log when it is dated `day` (fallback lines skipped)."""
    if not ORDERS.exists():
        return None
    for line in reversed(ORDERS.read_text(encoding="utf-8", errors="replace").splitlines()):
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("fallback"):
            continue
        return len(rec.get("orders", [])) if rec.get("date") == day.isoformat() else None
    return None


def alert(text: str) -> None:
    ok, detail = post_text(text)
    first = text.splitlines()[0]
    if ok:
        say(f"alert posted: {first}")
        return
    say(f"ALERT NOT SENT ({detail}): {first}")
    with open(ERRORS, "a") as fh:
        fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} daily-job alert could not be posted ({detail}): {first}\n")


def run_once(extra: list[str], timeout_min: int) -> int | None:
    """One run_daily.py run; its output goes to this process's stdout (the log). None = killed at the time limit."""
    p = subprocess.Popen([sys.executable, "-u", str(ROOT / "scripts" / "run_daily.py"), *extra], cwd=ROOT)
    try:
        return p.wait(timeout=timeout_min * 60)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        return None


def supervise(extra: list[str], pol: dr.Policy, run=run_once, now=datetime.now, sleep=time.sleep,
              notify=None) -> int:
    """The retry loop; returns the exit code for Task Scheduler (0, or the last run_daily code)."""
    notify = notify or alert
    first = now()
    attempt, warned = 0, False
    while True:
        attempt += 1
        if attempt > 1:
            say(f"attempt {attempt} of {pol.max_attempts}")
        log0, err0 = size(LOG), size(ERRORS)
        code = run(extra, pol.attempt_timeout_min)
        end = now()
        out = read_from(LOG, log0)
        new_err = [ln for ln in read_from(ERRORS, err0).splitlines() if ln.strip()]
        next_start = end + timedelta(minutes=pol.every_min)
        action = dr.decide(code, attempt, first, next_start, pol)

        if action == "done":
            texts = []
            if attempt > 1:
                texts.append(dr.recovered_text(attempt, end, todays_batch_size(end.date())))
            if new_err:
                texts.append(dr.finished_with_problems_text(new_err, end))
            if texts:
                notify("\n".join(texts))
            return 0

        why = dr.reason(code, out, new_err)
        say(f"attempt {attempt} stopped: {why}")
        if action == "safety_stop":
            notify(dr.safety_stop_text(why, end))
            return dr.SAFETY_EXIT
        if action == "give_up":
            notify(dr.give_up_text(why, attempt, end))
            return code or 1
        if not warned:
            notify(dr.first_stop_text(why, end, next_start, attempt, pol))
            warned = True
        say(f"retrying at {next_start:%H:%M}")
        sleep(max(0.0, (next_start - now()).total_seconds()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-alert", action="store_true", help="post one test message to the Discord channel and exit")
    args, extra = ap.parse_known_args()
    if args.test_alert:
        ok, detail = post_text("🔔 StockTrader alert test: the daily-job supervisor can reach this channel. "
                               "Real alerts appear here only when the evening run stops, recovers or gives up.")
        print(detail)
        return 0 if ok else 1
    live = (yaml.safe_load((ROOT / "config.yaml").read_text()) or {}).get("live", {})
    return supervise(extra, dr.policy_from_config(live))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:   # noqa: BLE001  (the supervisor itself failed: still try to tell someone)
        alert(f"🛑 **StockTrader daily-job supervisor crashed**: {type(e).__name__}: {str(e)[:300]}\n"
              f"Check data/run_daily.log; orders may not have been sent for the next open.")
        raise
