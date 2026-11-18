"""Run one cycle: mark, safety, forecast, exits, entries, record. Paper account only.

    python scripts/run_cycle.py                 a full cycle
    python scripts/run_cycle.py --no-forecast   mark and settle only (no Claude calls, a few seconds)
    python scripts/run_cycle.py --scan          show which markets pass the filters, forecast nothing, change nothing

Exit codes: 0 done, 3 skipped (quiet window, another cycle running, low memory), 4 safety stop, 1 error.
"""
import argparse
import sys
import time

from _bootstrap import ROOT

from src import runtime, safety, universe
from src.config import load_config
from src.forecast import make_backend
from src.ledger import Ledger
from src.trader import Trader
from src.venue import PolymarketUS


def scan(cfg, venue) -> int:
    st = universe.settings(cfg)
    listed = venue.list_markets(max_events=int(st.get("max_events_scanned", 300)))
    for m in listed:
        m.raw["lite"] = True
    keep, dropped = universe.choose(listed, cfg, {}, set())
    reasons = {}
    for why in dropped.values():
        key = why.split(" (")[0].split(" $")[0][:60]
        reasons[key] = reasons.get(key, 0) + 1
    print(f"{len(listed)} open markets listed, {len(keep)} pass the listing filters\n")
    for why, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  dropped {n:4d}  {why}")
    print("\nFirst candidates (order books not checked yet):")
    for m in keep[:20]:
        days = m.days_to_end()
        print(f"  {m.market_id[:48]:48s} {m.category or '-':14s} {days if days is None else round(days):>4} d  "
              f"liq ${m.liquidity or 0:>9,.0f}  {m.question[:70]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--no-forecast", action="store_true")
    ap.add_argument("--scan", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args.config)

    try:
        runtime.preflight(cfg, ROOT)
    except runtime.Busy as e:
        print(f"skipped: {e}")
        return 3

    rt = cfg.get("runtime") or {}
    venue = PolymarketUS(min_interval=float(rt.get("venue_min_interval_s", 0.5)))
    if args.scan:
        try:
            return scan(cfg, venue)
        except Exception as e:                       # the exchange is unreachable or changed its answer
            print(f"scan failed: {type(e).__name__}: {e}")
            return 1

    try:
        with runtime.Lock(ROOT / "data" / "cycle.lock", float(rt.get("lock_stale_hours", 3))):
            ledger = Ledger(ROOT / "data" / "pmt.db")
            try:
                if ledger.deposits() == 0 and not safety.is_live(cfg):
                    start = float((cfg.get("account") or {}).get("paper_bankroll", 1000.0))
                    ledger.deposit(start, "deposit: paper bankroll")
                    print(f"paper account opened with ${start:,.2f}")
                trader = Trader(cfg, ledger, venue, make_backend(cfg, ROOT), root=ROOT)
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
