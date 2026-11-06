"""The daily job: pull latest bars, score, apply rules, send orders.

Run after the close (config: live.schedule_local_time). Orders are market,
day-in-force, so they fill at the next open.

    python scripts/run_daily.py --dry-run          # PaperBroker, no API calls
    python scripts/run_daily.py                    # Alpaca paper (keys in .env)

State (last weights, exit dates) persists in data/live_state.json.
"""
import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

import _bootstrap  # noqa: F401
from dataclasses import replace

from src.backtest import BacktestConfig
from src.config import build_cost_model, build_rules, load_config
from src.costs import dollar_adv
from src.dataset import load_dataset
from src.features import compute_features, forward_excess_return, realized_vol
from src.portfolio import State, rebalance
from src.ranking import make_ranker, trailing_ic
from src.universe import apply_membership

STATE_PATH = Path("data/live_state.json")


def load_state() -> State:
    if not STATE_PATH.exists():
        return State()
    d = json.loads(STATE_PATH.read_text())
    return State(weights=pd.Series(d["weights"], dtype=float), last_exit={k: pd.Timestamp(v) for k, v in d["last_exit"].items()})


def save_state(s: State):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"weights": s.weights.round(6).to_dict(), "last_exit": {k: v.isoformat() for k, v in s.last_exit.items()}}, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--provider", default=None, choices=[None, "yfinance", "tiingo", "norgate"])
    args = ap.parse_args()

    cfg = load_config()
    p, m = cfg["portfolio"], cfg["model"]
    rules = build_rules(cfg)
    cost_model = build_cost_model(cfg)
    bt = BacktestConfig(ranker=m["type"], horizon_days=m["horizon_days"], train_window_days=m["train_window_days"])

    # If auto_tune ran in the last backtest, use the most recent tuned appetite live.
    tune_log = Path("data/tune_log.csv")
    if rules.optimizer and cfg.get("auto_tune", {}).get("enabled") and tune_log.exists():
        last = pd.read_csv(tune_log).iloc[-1]
        rules = replace(rules, optimizer=replace(rules.optimizer, risk_aversion=float(last["risk_aversion"]), tc_multiplier=float(last["tc_multiplier"])))
        print(f"Using tuned settings from {last['date']}: risk_aversion={last['risk_aversion']}, tc_multiplier={last['tc_multiplier']}")

    close, volume, raw_close, membership = load_dataset(cfg, provider=args.provider, refresh=True)
    today = close.index[-1]

    feats = compute_features(close, volume)
    labels = forward_excess_return(close, bt.horizon_days)
    ranker = make_ranker(bt.ranker)
    if ranker.needs_training:
        end = close.index[-1 - bt.horizon_days]
        ranker.fit(feats.loc[close.index[-bt.train_window_days]:end], labels, end_date=end)
    scores = ranker.score(feats.xs(today, level="date"))
    if membership is not None:
        latest_members = membership.iloc[-1]
        scores = scores[scores.index.isin(latest_members[latest_members].index)]
    vol = realized_vol(close, p["vol_lookback_days"]).loc[today]

    state = load_state()
    ret_win, ic = None, float("nan")
    if rules.sizing == "optimizer":
        ret_win = close.pct_change().iloc[-rules.optimizer.cov_lookback:]
        ic = trailing_ic(ranker, feats, labels, close.index, bt.horizon_days)
        print(f"Trailing IC: {ic:.3f}" if ic == ic else "Trailing IC: n/a (using ic_default)")
    adv_today = dollar_adv(raw_close, volume, 60).loc[today]
    new_w, trades, new_state = rebalance(scores, vol, rules, state, today, returns_window=ret_win, ic=ic,
                                         adv=adv_today, cost_model=cost_model)
    est_cost = cost_model.trade_cost(trades, adv_today, close.pct_change().iloc[-20:].std())
    print(f"Estimated cost of today's trades: {est_cost * 1e4:.1f} bps of portfolio")

    n_show = int((new_w > 0).sum()) if rules.sizing == "optimizer" else rules.top_n
    print(f"As of {today.date()} — {n_show} positions chosen:")
    print(scores.sort_values(ascending=False).head(max(n_show, 10)).round(3).to_string())
    print("\nTrades (Δ weight):")
    print(trades.round(4).to_string() if not trades.empty else "  none")

    from src.broker import make_broker
    from src.monitor import append_equity, write_ranking
    broker = make_broker("paper" if args.dry_run else "alpaca")
    if args.dry_run:
        broker.mark(raw_close.loc[today])
    orders = broker.submit_targets(new_w, raw_close.loc[today])
    equity = broker.equity()
    cash = equity - float(broker.positions().sum())
    print(f"\n{len(orders)} orders  |  equity ${equity:,.0f}")
    save_state(new_state)
    append_equity(today, equity, cash, int((new_w > 0).sum()))
    write_ranking(scores, new_w, state.weights, n_show)

    log = Path("data/orders.log")
    with open(log, "a") as f:
        f.write(json.dumps({"date": str(date.today()), "orders": orders}) + "\n")


if __name__ == "__main__":
    main()
