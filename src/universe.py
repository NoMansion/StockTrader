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


def apply_membership(scores: pd.Series, membership: pd.DataFrame | None, date: pd.Timestamp) -> pd.Series:
    """Keep only names that were in the universe on `date`."""
    if membership is None or date not in membership.index:
        return scores
    ok = membership.loc[date]
    return scores[ok.reindex(scores.index, fill_value=False).to_numpy()]
