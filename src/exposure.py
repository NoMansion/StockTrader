"""Market-regime exposure: a number in [0, 1] per day that scales how much of
the portfolio is invested (the rest sits in cash). Computed from the
equal-weight index of the point-in-time universe, so it needs no outside data.

Kinds (Nov 2026 sweep, 2001-2026 stitched results on the consistency setup):
    "vt15"         target 15% annualized vol: min(1, 0.15 / trailing-20d vol).
                   Best 26-year Sharpe (0.61 vs 0.55 unfiltered), max DD -32% vs -56%.
    "ret12m"       1 while the index is up over 252 days, else 0 (binary, whipsaws).
    "ret12m_half"  same but 0.5 instead of 0 (softer).
    "ma200"        1 above the 200-day MA, else 0.   "ma200_half": 0.5 below.
    "ret12m_ma200" (ret12m + ma200) / 2.
    "ret12m_vt15"  ret12m x vt15.   "ret12mhalf_vt15": ret12m_half x vt15.
Any "vtNN" works, NN = target vol in percent.
    "dd10half_vt15" vt15 x (0.5 while the index is >10% below its 1y high).
    "vt15_60" / "vt15_ema5" / "vt15_floor30": 60-day vol window / 5-day EMA smoothing / 30% floor.

A dict spec composes the same pieces (product of the components present):
    {"vt": 15, "vt_win": 20, "ret_days": 252, "ret_low": 0.5, "dd_thr": 0.10, "dd_low": 0.5,
     "ma": 200, "ma_low": 0.5, "ema": 5, "floor": 0.3}
e.g. portfolio.exposure: {vt: 15, ret_days: 252, ret_low: 0.5} == "ret12mhalf_vt15".

Breadth gates (Norgate index series, fetched through `EXT_LOADER`; sweep Nov 2026, both halves):
    "hl_days": N   0.5 ("hl_low") while NYSE new highs minus new lows summed over N days is < 0
                   (#NYSEHI - #NYSELO). N = 10 on top of ret12mhalf_vt15 + inverse-vol sizing:
                   stitched Sharpe 0.76 vs 0.73, max DD -13% vs -20%.
    "ad_ma": N     0.5 ("ad_low") while the NYSE cumulative A/D line (#NYSEAD) is below its N-day MA.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd


def universe_index(close: pd.DataFrame, membership: pd.DataFrame | None) -> pd.Series:
    """Equal-weight total-return index of each day's universe members (all names if no membership)."""
    rets = close.pct_change()
    if membership is not None:
        m = membership.reindex(index=close.index, columns=close.columns).ffill().fillna(False).astype(bool)
        rets = rets.where(m)
    bench = rets.mean(axis=1).fillna(0.0)
    return (1 + bench).cumprod()


STRING_SPECS = {
    "dd10half_vt15": {"vt": 15, "dd_thr": 0.10, "dd_low": 0.5},
    "vt15_60": {"vt": 15, "vt_win": 60},
    "vt15_40": {"vt": 15, "vt_win": 40},
    "vt15_ema5": {"vt": 15, "ema": 5},
    "vt15_floor30": {"vt": 15, "floor": 0.3},
    "ret12mhalf_vt15_60": {"vt": 15, "vt_win": 60, "ret_days": 252, "ret_low": 0.5},
    "ret6mhalf_vt15": {"vt": 15, "ret_days": 126, "ret_low": 0.5},
    "dd10_half": {"dd_thr": 0.10, "dd_low": 0.5},
}


GATE_SYMBOLS = {"hl_days": ["#NYSEHI", "#NYSELO"], "ad_ma": ["#NYSEAD"]}


def _default_loader(symbols: list[str]) -> pd.DataFrame:
    from src.providers_norgate import fetch_series
    return fetch_series(symbols)


# callable(symbols) -> DataFrame of daily closes (date index); swapped out in tests
EXT_LOADER = _default_loader


def external_series(symbols: list[str], index: pd.DatetimeIndex) -> pd.DataFrame:
    """Outside series aligned to the trading calendar (forward-filled, no look-ahead)."""
    df = EXT_LOADER(sorted(set(symbols)))
    df.index = pd.to_datetime(df.index)
    return df.reindex(df.index.union(index)).ffill().reindex(index)


def _gates(k: dict, index: pd.DatetimeIndex) -> pd.Series:
    """Multiplicative breadth gates (see module docstring). 1.0 when no gate key is present."""
    g = pd.Series(1.0, index=index)
    need = [s for key, syms in GATE_SYMBOLS.items() if k.get(key) is not None for s in syms]
    if not need:
        return g
    x = external_series(need, index)

    def flag(cond: pd.Series, low: float) -> pd.Series:
        return pd.Series(np.where(cond.fillna(False), low, 1.0), index=index)

    if k.get("hl_days") is not None:
        hl = (x["#NYSEHI"] - x["#NYSELO"]).rolling(int(k["hl_days"])).sum()
        g = g * flag(hl < 0, float(k.get("hl_low", 0.5)))
    if k.get("ad_ma") is not None:
        ad = x["#NYSEAD"]
        g = g * flag(ad < ad.rolling(int(k["ad_ma"])).mean(), float(k.get("ad_low", 0.5)))
    return g


def _spec(k: dict, idx: pd.Series) -> pd.Series:
    rets = idx.pct_change()
    e = _gates(k, idx.index)
    if k.get("vt"):
        v = rets.rolling(int(k.get("vt_win", 20))).std() * np.sqrt(252)
        e = e * (float(k["vt"]) / 100 / v).clip(upper=1.0).fillna(1.0)
    if k.get("ret_days"):
        e = e * pd.Series(np.where(idx.pct_change(int(k["ret_days"])) > 0, 1.0, float(k.get("ret_low", 0.5))), index=idx.index)
    if k.get("dd_thr"):
        dd = idx / idx.rolling(252, min_periods=60).max() - 1
        e = e * pd.Series(np.where(dd < -float(k["dd_thr"]), float(k.get("dd_low", 0.5)), 1.0), index=idx.index)
    if k.get("ma"):
        e = e * pd.Series(np.where(idx > idx.rolling(int(k["ma"])).mean(), 1.0, float(k.get("ma_low", 0.5))), index=idx.index)
    if k.get("ema"):
        e = e.ewm(span=int(k["ema"])).mean()
    if k.get("floor"):
        e = e.clip(lower=float(k["floor"]))
    return e.clip(upper=1.0)


def exposure_series(kind: str | dict, close: pd.DataFrame, membership: pd.DataFrame | None) -> pd.Series:
    idx = universe_index(close, membership)
    if isinstance(kind, dict):
        return _spec(kind, idx)
    if kind in STRING_SPECS:
        return _spec(STRING_SPECS[kind], idx)
    bvol = idx.pct_change().rolling(20).std() * np.sqrt(252)

    def vt(target_pct: float) -> pd.Series:
        return (target_pct / 100 / bvol).clip(upper=1.0).fillna(1.0)

    def ret12m(low: float) -> pd.Series:
        return pd.Series(np.where(idx.pct_change(252) > 0, 1.0, low), index=idx.index)

    def ma200(low: float) -> pd.Series:
        return pd.Series(np.where(idx > idx.rolling(200).mean(), 1.0, low), index=idx.index)

    if kind.startswith("vt") and kind[2:].isdigit():
        return vt(float(kind[2:]))
    if kind == "ret12m":
        return ret12m(0.0)
    if kind == "ret12m_half":
        return ret12m(0.5)
    if kind == "ma200":
        return ma200(0.0)
    if kind == "ma200_half":
        return ma200(0.5)
    if kind == "ret12m_ma200":
        return (ret12m(0.0) + ma200(0.0)) / 2
    if kind == "ret12m_vt15":
        return ret12m(0.0) * vt(15)
    if kind == "ret12mhalf_vt15":
        return ret12m(0.5) * vt(15)
    raise ValueError(f"unknown exposure kind: {kind}")


def scale_rules(rules, exposure: float):
    """Shrink the invested budget: cash_buffer' = 1 - e * (1 - cash_buffer)."""
    e = float(np.clip(exposure, 0.0, 1.0))
    return replace(rules, cash_buffer=1.0 - e * (1.0 - rules.cash_buffer))
