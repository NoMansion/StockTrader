"""Pull daily bars for the configured universe into the Parquet cache.

    python scripts/fetch_data.py                       # provider/universe from config.yaml
    python scripts/fetch_data.py --provider yfinance --universe static   # free dev run
"""
import argparse

import _bootstrap  # noqa: F401
from src.config import load_config
from src.dataset import load_dataset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=None, choices=[None, "yfinance", "tiingo", "norgate"])
    ap.add_argument("--universe", default=None, choices=[None, "static", "norgate", "liquidity"])
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if args.universe:
        cfg["data"]["universe"] = args.universe
    close, volume, _, membership = load_dataset(cfg, provider=args.provider, refresh=args.refresh)
    print(f"{close.shape[1]} tickers, {close.shape[0]} days, {close.index.min().date()} → {close.index.max().date()}")
    if membership is not None:
        n = membership.sum(axis=1)
        print(f"point-in-time universe: {int(n.min())}–{int(n.max())} members per day (mean {n.mean():.0f})")


if __name__ == "__main__":
    main()
