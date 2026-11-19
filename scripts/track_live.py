"""Live vs model: the account's daily return next to what the model's own decisions would have earned under the
backtest's execution assumptions (next-open fill, 10 bps per side). See src/tracking.py.

    python scripts/track_live.py               # every snapshot in data/targets/
    python scripts/track_live.py --bps 10      # cost the model charges per side
    python scripts/track_live.py --seed        # one-off: snapshot tonight's decision from the account + logs

Reads only (Alpaca account history + Norgate bars); never submits or cancels anything. Light: ~50 tickers.
Writes data/tracking.csv.
"""
import _bootstrap  # noqa: F401

import argparse
import json
import os
import re
from pathlib import Path

import pandas as pd

from src.tracking import TARGETS_DIR, load_snapshots, save_snapshot, summarize, track


def client():
    from dotenv import load_dotenv
    from alpaca.trading.client import TradingClient
    load_dotenv()
    paper = os.environ.get("ALPACA_PAPER", "true").lower() != "false"
    return TradingClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=paper)


def account_returns(c, start: pd.Timestamp) -> pd.Series:
    """Daily account return from Alpaca's portfolio history (profit/loss over the previous close's equity)."""
    from alpaca.trading.requests import GetPortfolioHistoryRequest
    h = c.get_portfolio_history(GetPortfolioHistoryRequest(timeframe="1D", start=(start - pd.Timedelta(days=7)).to_pydatetime()))
    idx = pd.to_datetime(h.timestamp, unit="s", utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
    eq = pd.Series(h.equity, index=idx, dtype="float64")
    pl = pd.Series(h.profit_loss, index=idx, dtype="float64")
    prev = eq.shift(1)
    return (pl / prev).dropna()


def seed(c):
    """Snapshot a decision that was made before run_daily saved snapshots: targets from live_state.json plus the
    sleeve line of the latest run in data/run_daily.log; holdings = the account now (before tomorrow's open);
    skip = target names with no open order."""
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    st = json.loads(Path("data/live_state.json").read_text())
    day = pd.Timestamp(st["last_rebalance"]).normalize()
    log = Path("data/run_daily.log").read_text(encoding="utf-8", errors="replace").splitlines()
    sl = [ln for ln in log if ln.startswith("Sleeve (")][-1]
    etf = {k: float(v) / 100 for k, v in re.findall(r"([A-Z]+) ([\d.]+)%", sl.split("->", 1)[1])}
    targets = pd.concat([pd.Series(st["weights"], dtype="float64"), pd.Series(etf, dtype="float64")])
    eq = float(c.get_account().equity)
    hold = pd.Series({p.symbol: float(p.market_value) for p in c.get_all_positions()}, dtype="float64") / eq
    ordered = {o.symbol for o in c.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))}
    skip = {t for t in targets.index if t not in ordered and t in hold.index}
    p = save_snapshot(day, hold, targets, skip, eq, source="seed (live_state + run_daily.log sleeve line)")
    print(f"seeded {p}: {len(targets)} targets ({targets.drop(list(etf)).sum():.1%} stocks), "
          f"{len(hold)} holdings, {len(skip)} skip")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bps", type=float, default=10.0)
    ap.add_argument("--out", default="data/tracking.csv")
    ap.add_argument("--seed", action="store_true")
    args = ap.parse_args()
    c = client()
    if args.seed:
        seed(c)
        return
    snaps = load_snapshots(TARGETS_DIR)
    if not snaps:
        print(f"no snapshots in {TARGETS_DIR} yet")
        return
    first = min(snaps)
    names = sorted(set().union(*[set(s["holdings"].index) | set(s["targets"].index) for s in snaps.values()]))
    from src.providers_norgate import fetch_bars
    bars = fetch_bars(names, start=str((first - pd.Timedelta(days=10)).date()))
    bars["adj_open"] = bars["open"] * bars["adj_close"] / bars["close"]
    adj_open = bars.pivot_table(index="date", columns="ticker", values="adj_open")
    adj_close = bars.pivot_table(index="date", columns="ticker", values="adj_close")
    actual = account_returns(c, first)
    df = track(snaps, adj_open, adj_close, actual, args.bps)
    if df.empty:
        print(f"{len(snaps)} snapshot(s), first {first.date()}: no trading day with prices after them yet")
        return
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    show = df.assign(actual_pct=df.actual_ret * 100, model_pct=df.model_ret * 100)
    print(show[["date", "actual_pct", "model_pct", "gap_bps", "turnover", "model_cost_bps", "stocks_target", "missing"]]
          .round(3).to_string(index=False))
    s = summarize(df)
    if s["days"]:
        te = f"{s['tracking_error_ann'] * 100:.2f}%" if s["tracking_error_ann"] is not None else "n/a (1 day)"
        print(f"\n{s['days']} day(s): actual {s['actual_total']:+.2%} vs model {s['model_total']:+.2%}; gap mean "
              f"{s['mean_gap_bps']:+.1f} bps/day (median {s['median_gap_bps']:+.1f}, worst {s['worst_gap_bps']:+.1f}); "
              f"tracking error {te} a year; mean turnover {s['mean_turnover']:.1%}")
        print("A gap near 0 means the account trades the way the backtest assumes; a steady negative gap is the "
              "extra cost of real fills.")


if __name__ == "__main__":
    main()
