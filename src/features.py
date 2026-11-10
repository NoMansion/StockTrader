"""Feature engineering on wide price/volume matrices.

All features at date t use only bars <= t. Labels use bars > t.
Features are cross-sectionally rank-normalized per date so the model learns
relative ordering rather than absolute levels.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_features(close: pd.DataFrame, volume: pd.DataFrame, raw_close: pd.DataFrame | None = None,
                     fundamentals: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """Return a long DataFrame indexed by (date, ticker) with raw feature columns.

    close: date x ticker adjusted close; volume: date x ticker volume.
    raw_close: unadjusted close, used for dollar volume (volume is unadjusted
    too); falls back to `close` when not given.
    fundamentals: optional {feature: date x ticker panel} (src/fundamentals.py), aligned to
    `close` and added as extra columns; names without data get the day's median.
    """
    px = raw_close if raw_close is not None else close
    ret = close.pct_change()
    feats = {
        # momentum at several horizons; skip the last 5 days (short-term reversal)
        "mom_21": close.pct_change(21),
        "mom_63": close.pct_change(63),
        "mom_126_skip5": close.shift(5) / close.shift(126) - 1,
        "mom_252_skip21": close.shift(21) / close.shift(252) - 1,
        # short-term reversal
        "rev_5": -close.pct_change(5),
        # volatility
        "vol_20": ret.rolling(20).std(),
        "vol_60": ret.rolling(60).std(),
        # volume relative to its own history
        "volu_ratio_20": volume / volume.rolling(20).mean(),
        "dollar_vol_60": np.log((px * volume).rolling(60).mean()),
        # distance from 52-week high
        "dist_52w_high": close / close.rolling(252).max() - 1,
        # max drawdown over 63d
        "dd_63": close / close.rolling(63).max() - 1,
        # path consistency: fraction of rolling 21d returns that were positive.
        # Rewards names that trended steadily rather than in one jump.
        "consistency_189": _consistency(close, 189),
        "consistency_252": _consistency(close, 252),
    }
    if fundamentals:
        from .fundamentals import align_to_prices
        for k, panel in fundamentals.items():
            feats[k] = align_to_prices(panel, close)
    long = pd.concat({k: v.stack() for k, v in feats.items()}, axis=1)
    long.index.names = ["date", "ticker"]
    return long


def _consistency(close: pd.DataFrame, window: int, ret_days: int = 21) -> pd.DataFrame:
    """Share of the trailing `window` days on which the `ret_days`-day return was positive."""
    r = close.pct_change(ret_days)
    return (r > 0).astype("float32").where(r.notna()).rolling(window, min_periods=window // 2).mean()


def rank_normalize(features: pd.DataFrame) -> pd.DataFrame:
    """Per-date winsorize (1/99 pct) then rank to [0, 1]. NaNs stay NaN."""
    def _one(df: pd.DataFrame) -> pd.DataFrame:
        lo, hi = df.quantile(0.01), df.quantile(0.99)
        clipped = df.clip(lo, hi, axis=1)
        return clipped.rank(pct=True)

    return features.groupby(level="date", group_keys=False).apply(_one)


def forward_excess_return(close: pd.DataFrame, horizon: int) -> pd.Series:
    """Label: return over next `horizon` days minus the cross-sectional mean.

    Uses close[t+h]/close[t]; strictly forward-looking, only for training.
    """
    fwd = close.shift(-horizon) / close - 1
    excess = fwd.sub(fwd.mean(axis=1), axis=0)
    s = excess.stack()
    s.index.names = ["date", "ticker"]
    s.name = "y"
    return s


def realized_vol(close: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """Annualized realized vol, used for position sizing."""
    return close.pct_change().rolling(lookback).std() * np.sqrt(252)
