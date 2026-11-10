"""Rankers: turn features into a per-date score (higher = more likely to outperform).

    MomentumRanker  — no ML baseline; the bar every model must clear.
    LGBMRanker      — LightGBM regression on rank-normalized features,
                      retrained walk-forward on a trailing window.

Both expose:
    fit(features, labels, end_date)   -> self      (no-op for the baseline)
    score(features_at_date)           -> pd.Series (ticker -> score)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import rank_normalize

LGBM_PARAMS = {
    "objective": "regression",
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.7,
    "bagging_fraction": 0.7,
    "bagging_freq": 1,
    "lambda_l2": 5.0,
    "verbose": -1,
    "seed": 7,
}


class MomentumRanker:
    """Score = 12-1 month momentum rank minus a small vol penalty."""

    name = "momentum"
    needs_training = False

    def fit(self, features: pd.DataFrame, labels: pd.Series, end_date=None):
        return self

    def score(self, feats: pd.DataFrame) -> pd.Series:
        r = feats.rank(pct=True)
        s = 0.6 * r["mom_252_skip21"] + 0.3 * r["mom_126_skip5"] - 0.1 * r["vol_60"]
        return s.dropna()


class LGBMRanker:
    """Cross-sectional LightGBM ranker. Requires `lightgbm`."""

    name = "lgbm"
    needs_training = True

    def __init__(self, params: dict | None = None, num_rounds: int = 400):
        self.params = {**LGBM_PARAMS, **(params or {})}
        self.num_rounds = num_rounds
        self.model = None
        self.cols: list[str] = []

    def fit(self, features: pd.DataFrame, labels: pd.Series, end_date=None):
        import lightgbm as lgb

        X = rank_normalize(features)
        df = X.join(labels, how="inner").dropna()
        if end_date is not None:
            df = df[df.index.get_level_values("date") <= end_date]
        if df.empty:
            raise ValueError("No training rows; check horizon / data range")
        self.cols = [c for c in df.columns if c != "y"]
        ds = lgb.Dataset(df[self.cols].values, label=df["y"].values)
        self.model = lgb.train(self.params, ds, num_boost_round=self.num_rounds)
        return self

    def score(self, feats: pd.DataFrame) -> pd.Series:
        if self.model is None:
            raise RuntimeError("fit() first")
        X = feats.rank(pct=True)[self.cols].dropna()
        return pd.Series(self.model.predict(X.values), index=X.index)


class BlendRanker:
    """Weighted sum of per-date percentile ranks of features. Negative weights
    penalize. The Nov 2026 sweep's winner is the "consistency" preset below."""

    name = "blend"
    needs_training = False

    def __init__(self, weights: dict[str, float]):
        if not weights:
            raise ValueError("BlendRanker needs a non-empty weights dict")
        self.weights = dict(weights)

    def fit(self, features: pd.DataFrame, labels: pd.Series, end_date=None):
        return self

    def score(self, feats: pd.DataFrame) -> pd.Series:
        r = feats.rank(pct=True)
        return sum(w * r[k] for k, w in self.weights.items()).dropna()


# Named blends. "consistency" = 12-1m momentum + 6m momentum + share of positive
# months over the past 9 months; found by the Nov 2026 sweep (best holdout Sharpe).
BLENDS: dict[str, dict[str, float]] = {
    "consistency": {"mom_252_skip21": 0.5, "mom_126_skip5": 0.2, "consistency_189": 0.3},
    "consistency_heavy": {"mom_252_skip21": 0.5, "mom_126_skip5": 0.1, "consistency_189": 0.4},
    "novol": {"mom_252_skip21": 0.6, "mom_126_skip5": 0.4},
    # Leader of the Nov 2026 sweep: consistency_heavy scaled to 70% plus a 30% free-cash-flow-yield
    # tilt. Stitched 26-yr Sharpe 1.00 / 10.6% CAGR / -18% drawdown with a 3-day rebalance, T-bill
    # yield on idle cash and the IEF/GLD sleeve (0.97 without the tilt). Needs model.fundamentals: sharadar.
    "c189f_fcfy30": {"mom_252_skip21": 0.35, "mom_126_skip5": 0.07, "consistency_189": 0.28, "fcf_yield": 0.3},
    # Earnings-surprise book (needs model.fundamentals: sharadar). Sweep 2026-11-09: 0.80 Sharpe on
    # the 2000s out of sample vs 0.72 for momentum; blending it INTO the momentum score did worse
    # than either alone, so it is meant to run as its own book (see portfolio.books).
    "earnings": {"sue": 1.0},
    # Leader since 2026-11-10: earnings surprise + free-cash-flow yield, 50/50, traded on liquidity ranks
    # 451-1000 (data.liquidity_band) with 40 names. Stitched 26-yr Sharpe 1.06 / 11.1% CAGR / -19% drawdown
    # (0.89 excess over T-bills vs 0.84 for c189f_fcfy30 on the top 450). Needs model.fundamentals: sharadar.
    "sue_fcfy": {"sue": 0.5, "fcf_yield": 0.5},
}


def make_ranker(kind: str, weights: dict[str, float] | None = None):
    """`kind`: "momentum" | "lgbm" | a BLENDS preset | "blend" (with `weights`)."""
    if kind == "momentum":
        return MomentumRanker()
    if kind == "lgbm":
        return LGBMRanker()
    if kind == "blend":
        return BlendRanker(weights or {})
    if kind in BLENDS:
        return BlendRanker(weights or BLENDS[kind])
    raise ValueError(f"unknown ranker: {kind}")


def trailing_ic(ranker, feats: pd.DataFrame, labels: pd.Series, dates: pd.DatetimeIndex, horizon: int, n: int = 126) -> float:
    """Mean realised IC of `ranker` over the last `n` dates whose labels have
    resolved (i.e. dates <= last_date - horizon). Used live to scale bets."""
    resolved = dates[: len(dates) - horizon][-n:]
    label_dates = set(labels.index.get_level_values("date"))
    feat_dates = set(feats.index.get_level_values("date"))
    ics = []
    for d in resolved:
        if d in label_dates and d in feat_dates:
            ics.append(information_coefficient(ranker.score(feats.xs(d, level="date")), labels.xs(d, level="date")))
    ics = [x for x in ics if np.isfinite(x)]
    return float(np.mean(ics)) if len(ics) >= 20 else np.nan


def information_coefficient(scores: pd.Series, labels: pd.Series) -> float:
    """Spearman rank correlation between scores and realized labels on one date."""
    j = pd.concat([scores.rename("s"), labels.rename("y")], axis=1).dropna()
    if len(j) < 5:
        return np.nan
    return j["s"].rank().corr(j["y"].rank())
