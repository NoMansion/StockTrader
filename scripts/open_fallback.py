"""Morning fallback for opening-auction orders (src/open_fallback.py). Scheduled weekdays every 3 min from 8:32 to
8:50 am CT ("StockTrader Open Fallback", scripts/open_fallback_hidden.vbs -> data/open_fallback.log): Alpaca marks
unfilled auction orders expired anywhere from 9:30:30 to 9:33+ ET, and an order still open when a run looks is only
resent by a later run.

    python scripts/open_fallback.py            # resend last night's unfilled auction orders as market orders
    python scripts/open_fallback.py --dry-run  # show what it would send, send nothing

Does nothing unless live.order_type is "opg" and live.open_fallback is true. Sends orders only while the market
is open, within live.open_fallback_window_min minutes of the open, for a batch logged on the previous session,
and never when the kill switch (data/STOP) exists or a real-money account lacks LIVE_TRADING_CONFIRM.
Each original order is resent at most once (data/fallback/<date>.json, saved after every order), and only one run
sends at a time (data/fallback/.lock), so the repeats never double an order.
"""
import _bootstrap  # noqa: F401

import argparse
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from src.open_fallback import batch_is_for_today, last_batch, plan_resends

ET = ZoneInfo("America/New_York")
LOCK = Path("data/fallback/.lock")
_held_lock = False


def take_lock(path: Path = LOCK, stale_s: float = 600) -> bool:
    """One sending run at a time: the task repeats every 3 min and two runs at once could resend the same order.
    A lock older than stale_s is left by a run that was killed and is taken over."""
    global _held_lock
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime > stale_s:
        path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    _held_lock = True
    return True


def release_lock(path: Path = LOCK) -> None:
    global _held_lock
    if _held_lock:
        path.unlink(missing_ok=True)
        _held_lock = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--test-at", default=None, help="dry-run test only: pretend it is this ET time ('2026-11-19 09:35')")
    args = ap.parse_args()
    if args.test_at:
        args.dry_run = True
    now = datetime.fromisoformat(args.test_at).replace(tzinfo=ET) if args.test_at else datetime.now(ET)
    print(f"===== open fallback {now:%Y-%m-%d %I:%M %p} ET{' (dry run)' if args.dry_run else ''} =====", flush=True)
    live = (yaml.safe_load(Path(args.config).read_text()) or {}).get("live", {})
    if live.get("order_type") != "opg" or not live.get("open_fallback", False):
        print(f"off (order_type {live.get('order_type')!r}, open_fallback {live.get('open_fallback', False)}): nothing to do")
        return
    window = int(live.get("open_fallback_window_min", 60))
    ks = Path((live.get("safety") or {}).get("kill_switch", "data/STOP"))
    if ks.exists():
        print(f"kill switch {ks} exists: no orders")
        return

    from dotenv import load_dotenv
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import GetCalendarRequest, MarketOrderRequest
    from src.safety import require_live_confirmation
    load_dotenv()
    paper = os.environ.get("ALPACA_PAPER", "true").lower() == "true"
    c = TradingClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=paper)

    if not args.test_at and not c.get_clock().is_open:
        print("market closed: nothing to do")
        return
    cal = c.get_calendar(GetCalendarRequest(start=now.date() - timedelta(days=10), end=now.date()))
    prev_session = max((d.date for d in cal if d.date < now.date()), default=None)
    today_open = next((d.open for d in cal if d.date == now.date()), None)
    if today_open is None:
        print("no session today in the calendar: nothing to do")
        return
    if isinstance(today_open, datetime):
        opened = today_open if today_open.tzinfo else today_open.replace(tzinfo=ET)
    else:                                   # a time of day
        opened = datetime.combine(now.date(), today_open, ET)
    mins = (now - opened).total_seconds() / 60
    if mins < 0 or mins > window:
        print(f"{mins:.0f} min after the open, outside the {window}-min window: nothing sent")
        return

    if not args.dry_run and not take_lock():
        print("another fallback run is still working: this one sends nothing")
        return
    batch = last_batch()
    if batch is None:
        print("no orders.log batch")
        return
    bdate = datetime.fromisoformat(batch["date"]).date()
    if not batch_is_for_today(bdate, prev_session, now.date()):
        print(f"last batch is from {bdate}, before the previous session {prev_session}: nothing to resend")
        return

    ids = [o["id"] for o in batch["orders"] if str(o.get("tif", "")).lower() == "opg" and o.get("id")]
    status = {}
    for oid in ids:
        try:
            o = c.get_order_by_id(oid)
            status[oid] = {"status": str(getattr(o.status, "value", o.status)), "qty": float(o.qty or 0),
                           "filled_qty": float(o.filled_qty or 0)}
        except Exception as ex:   # noqa: BLE001
            print(f"  could not read order {oid[:8]}: {str(ex)[:120]}")
    held = {p.symbol: float(p.qty) for p in c.get_all_positions()}
    done_path = Path("data/fallback") / f"{now.date()}.json"
    done = json.loads(done_path.read_text()) if done_path.exists() else {"resent": []}
    plan, notes = plan_resends(batch["orders"], status, held, already={r["orig_id"] for r in done["resent"]})
    n_opg = len(ids); n_filled = sum(1 for s in status.values() if s["status"].lower() == "filled")
    print(f"batch {bdate}: {n_opg} auction orders, {n_filled} filled, {len(plan)} to resend")
    for n in notes:
        print("  note:", n)
    if not plan:
        return
    for r in plan:
        print(f"  {r['side']:4s} {r['qty']:>6d} {r['ticker']:6s} (auction order {r['orig_status']})")
    if args.dry_run:
        print("dry run: nothing sent")
        return

    require_live_confirmation()
    done_path.parent.mkdir(parents=True, exist_ok=True)
    sent = []
    sells = [r for r in plan if r["side"] == "sell"]
    buys = [r for r in plan if r["side"] == "buy"]
    for group in (sells, buys):
        for r in group:
            req = MarketOrderRequest(symbol=r["ticker"], qty=r["qty"], side=OrderSide(r["side"]),
                                     time_in_force=TimeInForce.DAY)
            rec = {"ticker": r["ticker"], "side": r["side"], "tif": "day", "qty": r["qty"], "fallback_for": r["orig_id"]}
            try:
                o = c.submit_order(req)
                rec["id"] = str(o.id)
            except Exception as ex:   # noqa: BLE001
                rec["id"] = None; rec["error"] = str(ex)[:200]
                print(f"  rejected {r['side']} {r['ticker']}: {str(ex)[:140]}")
            sent.append(rec)
            done["resent"].append({"orig_id": r["orig_id"], "new_id": rec.get("id")})
            done_path.write_text(json.dumps(done, indent=1))   # after every order: a crash never leads to a resend
        if group is sells and sells:
            time.sleep(5)      # let the sells fill before the buys use the cash
    with open("data/orders.log", "a") as f:
        f.write(json.dumps({"date": str(now.date()), "fallback": True, "orders": sent}) + "\n")
    ok = sum(1 for s in sent if s.get("id"))
    print(f"sent {ok} of {len(sent)} fallback orders")
    if ok < len(sent):
        with open("data/run_daily_errors.log", "a") as f:
            f.write(f"{now:%Y-%m-%d %H:%M} ET open fallback: {len(sent) - ok} of {len(sent)} resends rejected\n")


if __name__ == "__main__":
    try:
        main()
    finally:
        release_lock()
