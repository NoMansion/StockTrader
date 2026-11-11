"""Universe definition.

Three modes, chosen by `data.universe` in config.yaml:

  static   — the hand list below (or a CSV). Fine for dev; survivorship-biased.
  norgate  — point-in-time index membership from Norgate (Platinum+). Returns
             every symbol that was EVER in the index over the window, plus a
             date x ticker membership matrix so the backtest only trades names
             that were members on that day.
  liquidity — rule-based: on each rebalance date, the top-K names by trailing
             median dollar volume with price above a floor, evaluated only on
             data available that day. Works with any provider that includes
             delisted names (Norgate, Sharadar).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

STARTER_UNIVERSE = [
    # Tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "AVGO", "ORCL", "CRM", "ADBE",
    "AMD", "INTC", "CSCO", "QCOM", "TXN",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "V", "MA",
    # Health
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "AMGN",
    # Consumer
    "WMT", "COST", "HD", "LOW", "MCD", "SBUX", "NKE", "PG", "KO", "PEP",
    # Industrials / energy / other
    "CAT", "DE", "HON", "UNP", "UPS", "BA", "GE", "XOM", "CVX", "COP",
    "NEE", "DUK", "LIN", "DIS", "NFLX", "T", "VZ",
]


def load_universe(csv_path: str | Path | None = None) -> list[str]:
    """Static list. If a CSV path is given it must have a `ticker` column."""
    if csv_path:
        df = pd.read_csv(csv_path)
        return sorted(df["ticker"].astype(str).str.upper().unique().tolist())
    return sorted(set(STARTER_UNIVERSE))


def norgate_universe(index_name: str, start: str) -> tuple[list[str], pd.DataFrame]:
    """(all symbols ever in the index since `start`, date x ticker membership)."""
    from .providers_norgate import list_symbols, point_in_time_universe

    syms = list_symbols(include_delisted=True)
    membership = point_in_time_universe(syms, index_name, start)
    if membership.empty:
        raise RuntimeError(f"No constituent history for '{index_name}' — Platinum/Diamond subscription required")
    return sorted(membership.columns.tolist()), membership


def liquidity_membership(close: pd.DataFrame, volume: pd.DataFrame, top_k: int = 500, min_price: float = 5.0, lookback: int = 60) -> pd.DataFrame:
    """date x ticker membership: top_k by trailing median dollar volume, price >= min_price.

    Uses only data up to each date (rolling), so it is point-in-time by construction.
    """
    dv = (close * volume).rolling(lookback, min_periods=lookback // 2).median()
    eligible = dv.where(close >= min_price)
    rank = eligible.rank(axis=1, ascending=False)
    return (rank <= top_k).fillna(False)


def trim_to_universe(close: pd.DataFrame, volume: pd.DataFrame, raw_close: pd.DataFrame | None,
                     membership: pd.DataFrame | None, keep=()):
    """Drop tickers that were never universe members (plus `keep`, e.g. names still held).

    Two reasons. Memory: Norgate returns ~12,000 names since 2010 and the feature frame is built for every
    column; untrimmed, the daily job ran a 16 GB machine out of memory and froze it (2026-11-11). Fidelity: the
    sweep that validated the live model trims the same way, and percentile ranks and median fills are taken
    over whatever columns are present, so the live ranking must see the same cross-section.
    Returns (close, volume, raw_close, membership) restricted to the kept columns, in membership order."""
    if membership is None:
        return close, volume, raw_close, membership
    ever = membership.any(axis=0)
    cols = [c for c in ever[ever].index if c in close.columns]
    seen = set(cols)
    cols += [c for c in sorted(keep) if c not in seen and c in close.columns]
    return (close[cols], volume[cols], raw_close[cols] if raw_close is not None else None,
            membership.reindex(columns=cols, fill_value=False))


def trade_membership(data_cfg: dict, raw_close: pd.DataFrame, volume: pd.DataFrame,
                     membership: pd.DataFrame | None) -> pd.DataFrame | None:
    """Apply `data.liquidity_band: [lo, hi]`: trade only liquidity ranks lo+1..hi of the top-`hi`
    universe (the dataset must be loaded with liquidity_top_k = hi). Only ranking and selection are
    restricted; the exposure gates keep the full top-`hi` universe, which measures the broad market.
    Sweep 2026-11-10: the SUE + FCF-yield ranker on ranks 451-1000 beat every top-450 setup."""
    band = data_cfg.get("liquidity_band")
    if not band or membership is None:
        return membership
    lo, hi = int(band[0]), int(band[1])
    top_k = int(data_cfg.get("liquidity_top_k", 500))
    if not 0 < lo < hi or top_k != hi:
        raise ValueError(f"data.liquidity_band {band!r} needs 0 < lo < hi and liquidity_top_k == hi (got {top_k})")
    top = liquidity_membership(raw_close, volume, top_k=lo, min_price=float(data_cfg.get("min_price", 5.0)))
    top = top.reindex_like(membership).fillna(False).astype(bool)
    return membership & ~top


def apply_membership(scores: pd.Series, membership: pd.DataFrame | None, date: pd.Timestamp) -> pd.Series:
    """Keep only names that were in the universe on `date`."""
    if membership is None or date not in membership.index:
        return scores
    ok = membership.loc[date]
    return scores[ok.reindex(scores.index, fill_value=False).to_numpy()]
