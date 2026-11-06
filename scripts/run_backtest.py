"""Backtest the configured strategy and print a summary.

    python scripts/run_backtest.py                  # momentum baseline
    python scripts/run_backtest.py --model lgbm     # walk-forward LightGBM
    python scripts/run_backtest.py --top-n 10 --rebalance 5
"""
import argparse
import json

import _bootstrap  # noqa: F401
from src.backtest import run_backtest
from src.config import build_backtest_config, build_rules, load_config
from src.dataset import load_dataset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, choices=[None, "momentum", "lgbm"])
    ap.add_argument("--provider", default=None, choices=[None, "yfinance", "tiingo", "norgate"])
    ap.add_argument("--universe", default=None, choices=[None, "static", "norgate", "liquidity"])
    ap.add_argument("--top-n", type=int, default=None)
    ap.add_argument("--rebalance", type=int, default=None, help="rebalance every N days")
    ap.add_argument("--sizing", default=None, choices=[None, "optimizer", "rank", "equal", "inverse_vol"])
    ap.add_argument("--no-tune", action="store_true", help="disable auto_tune for this run")
    ap.add_argument("--flat-costs", action="store_true", help="use the flat slippage model instead of impact")
    ap.add_argument("--capital", type=float, default=None, help="account size in $ for the impact cost model")
    ap.add_argument("--out", default="data/backtest_daily.csv")
    args = ap.parse_args()

    cfg = load_config()
    if args.sizing:
        cfg["portfolio"]["sizing"] = args.sizing
    if args.universe:
        cfg["data"]["universe"] = args.universe
    if args.no_tune:
        cfg.setdefault("auto_tune", {})["enabled"] = False
    if args.flat_costs:
        cfg.setdefault("costs", {})["model"] = "flat"
    if args.capital:
        cfg.setdefault("costs", {})["capital"] = args.capital
    rules = build_rules(cfg, top_n=args.top_n)
    bt = build_backtest_config(cfg, ranker=args.model, rebalance=args.rebalance)

    close, volume, _, membership = load_dataset(cfg, provider=args.provider)

    res = run_backtest(close, volume, rules, bt, membership=membership)
    res.daily.to_csv(args.out)
    if not res.tune_log.empty:
        res.tune_log.to_csv("data/tune_log.csv", index=False)
    print(json.dumps(res.summary(), indent=2, default=str))
    print(f"\nDaily series written to {args.out}")


if __name__ == "__main__":
    main()
