"""One call that turns config into (close, volume, raw_close, membership).

Handles the three universe modes so scripts don't repeat the logic:
  static    — hand list / CSV, no membership matrix
  norgate   — index constituents over time (Platinum+), membership from Norgate
  liquidity — all symbols from the provider, membership by rolling dollar volume
"""
from __future__ import annotations

import gc

import pandas as pd

from .data import load_wide
from .universe import liquidity_membership, load_universe, norgate_universe


def load_dataset(cfg: dict, provider: str | None = None, refresh: bool = False):
    d = cfg["data"]
    provider = provider or d.get("provider", "yfinance")
    mode = d.get("universe", "static")
    start = d["start"]
    membership = None

    if mode == "norgate":
        if provider != "norgate":
            raise ValueError("universe: norgate requires provider: norgate")
        tickers, membership = norgate_universe(d.get("index_name", "S&P 500"), start)
    elif mode == "liquidity":
        if provider == "norgate":
            from .providers_norgate import list_symbols
            tickers = list_symbols(include_delisted=True)
        else:
            tickers = load_universe(d.get("universe_csv"))
    elif mode == "static":
        tickers = load_universe(d.get("universe_csv"))
    else:
        raise ValueError(f"unknown universe mode: {mode}")

    # straight to the three matrices (same values as load_bars + to_wide, a fraction of the memory peak)
    w = load_wide(tickers, start, ["adj_close", "volume", "close"], provider=provider, cache_dir=d["cache_dir"],
                  refresh=refresh)
    gc.collect()
    close, volume, raw_close = w["adj_close"], w["volume"], w["close"]
    del w

    if mode == "liquidity":
        # Rank on RAW close x raw volume. Split-adjusted close x unadjusted
        # volume is meaningless, and for serial reverse-splitters the adjusted
        # price is inflated by orders of magnitude, which pulled sub-dollar
        # pink-sheet names into the "most liquid 1000" and past the price floor.
        membership = liquidity_membership(
            raw_close, volume, top_k=d.get("liquidity_top_k", 500), min_price=d.get("min_price", 5.0),
        )
        if provider == "norgate":
            # drop days where a name was only OTC-listed (Platinum includes those)
            from .providers_norgate import major_exchange_membership
            mx = major_exchange_membership(list(close.columns), start)
            if not mx.empty:
                mx = mx.reindex(index=close.index, columns=close.columns).ffill().fillna(False).astype(bool)
                membership = membership & mx
    return close, volume, raw_close, membership
