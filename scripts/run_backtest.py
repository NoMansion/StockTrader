"""Backtest the configured strategy and print a summary.

    python scripts/run_backtest.py                  # momentum baseline
    python scripts/run_backtest.py --model lgbm     # walk-forward LightGBM
    python scripts/run_backtest.py --top-n 10 --rebalance 5
"""
import argparse
import json

import _bootstrap  # noqa: F401
from src.backtest import run_backtest
from src.books import build_books, run_books
from src.config import build_backtest_config, build_rules, load_config
from src.dataset import load_dataset
from src.exposure import exposure_series
from src.providers_sharadar import fundamentals_from_config
from src.universe import trade_membership, trim_to_universe
from src.ranking import BLENDS
from src.sectors import load_sectors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, choices=[None, "momentum", "lgbm", *BLENDS])
    ap.add_argument("--sector-mode", default=None, choices=[None, "equal", "cap", "none"],
                    help="override portfolio.sector_mode ('none' disables it; 'cap' uses portfolio.sector_cap)")
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
    if args.sector_mode:
        cfg["portfolio"]["sector_mode"] = None if args.sector_mode == "none" else args.sector_mode
    bt = build_backtest_config(cfg, ranker=args.model, rebalance=args.rebalance)

    close, volume, raw_close, membership = load_dataset(cfg, provider=args.provider)
    close, volume, raw_close, membership = trim_to_universe(close, volume, raw_close, membership)   # as the sweep and the daily job do

    sectors = None
    if cfg["portfolio"].get("sector_mode"):
        ever = membership.columns[membership.any(axis=0)] if membership is not None else close.columns
        sectors = load_sectors(sorted(ever))
    rules = build_rules(cfg, top_n=args.top_n, sectors=sectors)
    expo = exposure_series(cfg["portfolio"]["exposure"], close, membership) if cfg["portfolio"].get("exposure") else None
    membership = trade_membership(cfg["data"], raw_close, volume, membership)   # gates above see the full universe

    fund = fundamentals_from_config(cfg, close)

    books = build_books(cfg)
    kw = dict(membership=membership, raw_close=raw_close, exposure=expo, fundamentals=fund)
    if books:
        print("Books: " + ", ".join(f"{b.name} ({b.ranker}, {b.weight:.0%}, top {b.top_n or rules.top_n})" for b in books))
        res = run_books(close, volume, rules, bt, books, **kw)
    else:
        res = run_backtest(close, volume, rules, bt, **kw)
    res.daily.to_csv(args.out)
    if not res.tune_log.empty:
        res.tune_log.to_csv("data/tune_log.csv", index=False)
    print(json.dumps(res.summary(), indent=2, default=str))
    print(f"\nDaily series written to {args.out}")


if __name__ == "__main__":
    main()
