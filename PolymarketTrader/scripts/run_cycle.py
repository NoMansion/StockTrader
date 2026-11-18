"""Run one cycle: mark, safety, forecast, exits, entries, record. Paper account only.

    python scripts/run_cycle.py                 a full cycle
    python scripts/run_cycle.py --no-forecast   mark and settle only (no Claude calls, a few seconds)
    python scripts/run_cycle.py --scan          show which markets pass the filters, forecast nothing, change nothing

Exit codes: 0 done, 3 skipped (quiet window, another cycle running, low memory), 4 safety stop, 1 error.
"""
import argparse
import re
import sys
import time

from _bootstrap import ROOT

from src import runtime, safety, universe
from src.config import load_config
from src.forecast import make_backend
from src.ledger import Ledger
from src.trader import Trader
from src.kalshi import Kalshi
from src.venue import PolymarketUS, brief


def scan(cfg, venue) -> int:
    st = universe.settings(cfg)
    cats = list(st["categories_allow"]) or None
    listed = venue.list_markets(max_events=int(st["max_events_scanned"]), categories=cats,
                                min_days=float(st["min_days_to_resolution"]), max_days=float(st["max_days_to_resolution"]))
    for m in listed:
        m.raw["lite"] = True
    keep, dropped = universe.choose(listed, cfg, {}, set())
    reasons = {}
    for why in dropped.values():
        key = re.sub(r"[-+]?\d[\d,.]*", "N", why)[:70]          # group "208 days ..." with "159 days ..."
        reasons[key] = reasons.get(key, 0) + 1
    print(f"{len(listed)} open markets listed in {', '.join(cats) if cats else 'all categories'}; "
          f"{len(keep)} pass the listing filters ({venue.requests} requests)\n")
    for why, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  dropped {n:5d}  {why}")
    print("\nCandidates in forecast order (order books not checked yet):")
    for m in keep[:40]:
        days = m.days_to_end()
        print(f"  {m.category or '-':11s} {days if days is None else round(days):>3} d  {m.best_bid:.3f}/{m.best_ask:.3f}  "
              f"{m.question[:84]}")
    return 0


def make_venue(cfg):
    rt = cfg.get("runtime") or {}
    name = str((cfg.get("account") or {}).get("venue", "kalshi")).lower()
    pace = float(rt.get("venue_min_interval_s", 1.0))
    if name == "kalshi":
        return Kalshi(min_interval=pace, cache_dir=ROOT / "data")
    if name == "polymarket_us":
        return PolymarketUS(min_interval=pace)
    raise ValueError(f"unknown account.venue {name!r} (kalshi or polymarket_us)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--no-forecast", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--db", default=None, help="ledger file (default data/pmt.db); use another for a trial run")
    args = ap.parse_args()
    cfg = load_config(args.config)

    try:
        runtime.preflight(cfg, ROOT)
    except runtime.Busy as e:
        print(f"skipped: {e}")
        return 3

    rt = cfg.get("runtime") or {}
    venue = make_venue(cfg)
    if args.scan:
        try:
            return scan(cfg, venue)
        except Exception as e:                       # the exchange is unreachable or changed its answer
            print(f"scan failed: {brief(e)}")
            return 1

    try:
        with runtime.Lock(ROOT / "data" / "cycle.lock", float(rt.get("lock_stale_hours", 1))) as lock:
            ledger = Ledger(args.db or ROOT / "data" / "pmt.db")
            try:
                if ledger.deposits() == 0 and not safety.is_live(cfg):
                    start = float((cfg.get("account") or {}).get("paper_bankroll", 1000.0))
                    ledger.deposit(start, "deposit: paper bankroll")
                    print(f"paper account opened with ${start:,.2f}")
                trader = Trader(cfg, ledger, venue, make_backend(cfg, ROOT), root=ROOT, heartbeat=lock.touch)
                t0 = time.time()
                res = trader.run(do_forecast=not args.no_forecast)
                print("\n".join(res.log))
                s = res.stats
                print(f"\ncycle {res.run_id}: {res.status} in {time.time() - t0:,.0f} s | equity ${s.get('equity', 0):,.2f} "
                      f"| cash ${s.get('cash', 0):,.2f} | {s.get('positions', 0)} positions, {s.get('resting', 0)} resting orders "
                      f"| {s.get('forecasts', 0)} forecasts, {s.get('orders', 0)} orders")
                return safety.EXIT_CODE if res.status == "stopped" else 0
            finally:
                ledger.close()
    except runtime.Busy as e:
        print(f"skipped: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
