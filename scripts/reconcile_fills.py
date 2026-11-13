"""Compare Alpaca fills with the backtest's assumption (next open, 10 bps).

    python scripts/reconcile_fills.py              # every order in data/orders.log
    python scripts/reconcile_fills.py --days 30    # recent submissions only

Reads only (order queries + Norgate bars); never submits or cancels anything.
Writes data/fills.csv and prints the slippage summary.
"""
import _bootstrap  # noqa: F401

import argparse

import pandas as pd

from src.reconcile import fills_frame, orders_from_log, slippage, summarize


def all_closed_orders(client, after, GetOrdersRequest, QueryOrderStatus, page: int = 500) -> list:
    """Every closed order since `after`. Alpaca returns at most 500 per call, so page forward by submission time
    (bug audit 2026-11-13: one call silently dropped everything past the 500th order, ~10 trading days)."""
    out, seen = [], set()
    while True:
        batch = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after, limit=page, direction="asc"))
        new = [o for o in batch if str(o.id) not in seen]
        out += new
        seen |= {str(o.id) for o in new}
        if len(batch) < page or not new:
            return out
        # step back 1 s so orders sharing the boundary timestamp are not skipped; `seen` drops the repeats
        after = (max(pd.Timestamp(o.submitted_at) for o in batch) - pd.Timedelta(seconds=1)).to_pydatetime()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="data/orders.log")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--out", default="data/fills.csv")
    ap.add_argument("--model-bps", type=float, default=10.0, help="per-side cost the backtest charges")
    args = ap.parse_args()

    log = orders_from_log(args.log, days=args.days)
    if log.empty:
        print("no order ids in the log yet")
        return
    print(f"{len(log)} orders logged over {log['submit_date'].nunique()} days "
          f"({log['submit_date'].min().date()} .. {log['submit_date'].max().date()})")

    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest
    from src.broker import AlpacaBroker
    client = AlpacaBroker().client
    after = (log["submit_date"].min() - pd.Timedelta(days=1)).to_pydatetime()
    alp = all_closed_orders(client, after, GetOrdersRequest, QueryOrderStatus)
    print(f"{len(alp)} closed orders at Alpaca since {after.date()}")
    fills = fills_frame(alp, log)
    if fills.empty:
        print("none of the logged orders are closed at Alpaca yet")
        return
    print(f"{int((fills['qty'] > 0).sum())} filled, {int((fills['qty'] == 0).sum())} unfilled/cancelled "
          f"({', '.join(sorted(set(fills.loc[fills['qty'] == 0, 'status'])))})" if (fills["qty"] == 0).any() else
          f"{len(fills)} filled")

    from src.providers_norgate import fetch_bars
    done = fills[fills["qty"] > 0]
    bars = fetch_bars(sorted(done["ticker"].unique()), start=str((done["fill_date"].min() - pd.Timedelta(days=10)).date()))
    sl = slippage(fills, bars)
    sl.to_csv(args.out, index=False)
    s = summarize(sl, model_bps=args.model_bps)
    print(f"\nFills with a Norgate reference: {s.get('priced', 0)}/{s['orders']}  (written to {args.out})")
    if s.get("priced"):
        print(f"  slippage vs fill-day open:   mean {s['bps_open_mean']:+.1f} bps, median {s['bps_open_median']:+.1f}, "
              f"notional-weighted {s['bps_open_weighted']:+.1f}")
        print(f"  vs prior close (weighted):   {s['bps_close_weighted']:+.1f} bps  (overnight gap + slippage)")
        print(f"  filled within 5 min of open: {s['share_filled_within_5min_of_open']:.0%}")
        print(f"  backtest charges {s['model_bps']:.0f} bps per side -> live fills were "
              f"{abs(s['excess_vs_model_bps']):.1f} bps {'worse' if s['excess_vs_model_bps'] > 0 else 'better'} than modelled")
        worst = sl.dropna(subset=["bps_open"]).reindex(sl["bps_open"].abs().sort_values(ascending=False).index).head(5)
        print("\n  largest deviations from the open:")
        for r in worst.itertuples():
            print(f"    {r.fill_date.date()} {r.ticker:6s} {r.side:4s} {r.qty:9.3f} @ {r.price:9.2f}  open {r.open:9.2f}  {r.bps_open:+7.1f} bps")


if __name__ == "__main__":
    main()
