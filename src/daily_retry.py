"""Retry policy and alert texts for the scheduled daily job. Pure logic, no I/O, so it can be tested;
scripts/run_daily_retry.py runs the job and posts the alerts.

run_daily.py exit codes and what the supervisor does:
    0      finished: orders sent, or nothing to do (holiday, hold day)       -> stop
    3      memory guard stopped it, or the price data was not current yet    -> retry
    4      safety limit (kill switch, equity / turnover / order-size checks) -> never retried (it would only stop
                                                                                 again); alert right away
    other  crash, or the attempt ran past its time limit (code None)         -> retry
Retries wait live.retry.every_min after an attempt ends, stop after live.retry.max_attempts runs, and never start
after live.retry.last_start (local time) or on a later local date: orders.log is filed under the local date, so a
run after midnight would be filed under the wrong day and the morning fallback would skip its auction orders.
A retry is safe: run_daily cancels the account's open orders before sending and sizes from actual positions,
and a run that already rebalanced today only holds.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import time as dtime

SAFETY_EXIT = 4


@dataclass(frozen=True)
class Policy:
    every_min: int = 30
    max_attempts: int = 6
    last_start: dtime = dtime(22, 0)
    attempt_timeout_min: int = 90


def policy_from_config(live: dict | None) -> Policy:
    r = (live or {}).get("retry") or {}
    d = Policy()
    last = r.get("last_start")
    return Policy(every_min=int(r.get("every_min", d.every_min)),
                  max_attempts=int(r.get("max_attempts", d.max_attempts)),
                  last_start=dtime.fromisoformat(str(last)) if last else d.last_start,
                  attempt_timeout_min=int(r.get("attempt_timeout_min", d.attempt_timeout_min)))


def decide(code: int | None, attempt: int, first_start: datetime, next_start: datetime, policy: Policy) -> str:
    """What to do after attempt number `attempt` (1-based) ended with `code` (None = killed at the time limit).
    Returns "done", "safety_stop", "retry" or "give_up"."""
    if code == 0:
        return "done"
    if code == SAFETY_EXIT:
        return "safety_stop"
    if attempt >= policy.max_attempts:
        return "give_up"
    if next_start.date() != first_start.date() or next_start.time() > policy.last_start:
        return "give_up"
    return "retry"


def reason(code: int | None, output: str, new_errors: list[str]) -> str:
    """One line on why an attempt did not finish: the job's own words where it left any."""
    for line in reversed(output.splitlines()):
        if line.strip().startswith("MEMORY GUARD:"):
            return line.strip().split(". Stopping")[0] + " (memory guard)"
    if new_errors:
        return _strip_stamp(new_errors[-1])
    if code is None:
        return "the run did not finish within its time limit and was stopped"
    tail = [ln.strip() for ln in output.splitlines() if ln.strip()]
    return f"exit code {code}" + (f": {tail[-1][:300]}" if tail else "")


def _strip_stamp(line: str) -> str:
    """'2026-11-19 17:31:02 no trading: ...' -> 'no trading: ...'"""
    parts = line.split(" ", 2)
    if len(parts) == 3 and len(parts[0]) == 10 and parts[0][4] == "-" and ":" in parts[1]:
        return parts[2]
    return line


def _t(dt: datetime) -> str:
    return f"{dt:%I:%M %p}".lstrip("0") + " CT"


def first_stop_text(why: str, at: datetime, retry_at: datetime, attempt: int, policy: Policy) -> str:
    return (f"⚠️ **StockTrader daily job stopped** at {_t(at)}: {why}\n"
            f"No orders have been sent for the next open yet. Retrying at {_t(retry_at)} "
            f"(attempt {attempt + 1} of {policy.max_attempts}). If it was the memory guard, free RAM before then.")


def recovered_text(attempt: int, at: datetime, n_orders: int | None) -> str:
    what = (f"{n_orders} orders are queued for the next open" if n_orders is not None
            else "no new order batch was logged (a hold day or a holiday?)")
    return f"✅ **StockTrader daily job recovered**: attempt {attempt} finished at {_t(at)}; {what}."


def give_up_text(why: str, attempts: int, at: datetime) -> str:
    return (f"🛑 **StockTrader daily job gave up** at {_t(at)} after {attempts} attempt(s). Last stop: {why}\n"
            f"**No orders were sent for the next open.** To trade tomorrow, fix the cause and run "
            f"`.venv\\Scripts\\python.exe scripts\\run_daily.py` before midnight CT.")


def safety_stop_text(why: str, at: datetime) -> str:
    return (f"🛑 **StockTrader safety stop** at {_t(at)}: {why}\n"
            f"No orders were sent for the next open, and the job is not retried (it would stop again). "
            f"Details in data/run_daily_errors.log.")


def finished_with_problems_text(lines: list[str], at: datetime) -> str:
    body = "\n".join(f"• {_strip_stamp(x)[:300]}" for x in lines[-8:])
    return f"⚠️ **StockTrader daily job finished at {_t(at)} but logged problems:**\n{body}"
