import numpy as np
import pandas as pd
import pytest

from src.features import compute_features
from src.ranking import BLENDS, BlendRanker, make_ranker


def _panel(n_days=320, n=6, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n_days)
    cols = [f"T{i}" for i in range(n)]
    close = pd.DataFrame(np.exp(rng.normal(0, 0.01, (n_days, n)).cumsum(0)) * 50, index=idx, columns=cols)
    vol = pd.DataFrame(rng.integers(1e5, 1e6, (n_days, n)), index=idx, columns=cols).astype(float)
    return close, vol


def test_consistency_feature_is_a_share_in_unit_interval_and_monotone_trend_scores_one():
    close, vol = _panel()
    close["T0"] = np.linspace(10, 20, len(close))          # straight up: every 21d return positive
    f = compute_features(close, vol)
    last = f.xs(close.index[-1], level="date")
    assert set(["consistency_189", "consistency_252"]) <= set(f.columns)
    assert last["consistency_189"].between(0, 1).all()
    assert last.loc["T0", "consistency_189"] == pytest.approx(1.0)


def test_blend_ranker_weights_percentile_ranks():
    feats = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]}, index=["X", "Y", "Z"])
    s = BlendRanker({"a": 1.0}).score(feats)
    assert list(s.sort_values(ascending=False).index) == ["Z", "Y", "X"]
    s = BlendRanker({"a": 0.5, "b": -0.5}).score(feats)          # b penalised -> same order, stronger
    assert list(s.sort_values(ascending=False).index) == ["Z", "Y", "X"]
    assert BlendRanker({"a": 0.5, "b": 0.5}).score(feats).nunique() == 1   # offsetting -> flat


def test_make_ranker_presets_and_overrides():
    assert make_ranker("consistency").weights == BLENDS["consistency"]
    assert make_ranker("blend", {"mom_63": 1.0}).weights == {"mom_63": 1.0}
    assert make_ranker("consistency", {"mom_63": 1.0}).weights == {"mom_63": 1.0}
    with pytest.raises(ValueError):
        make_ranker("blend")
    with pytest.raises(ValueError):
        make_ranker("nope")


def test_preset_scores_real_features_without_nans_at_the_end():
    close, vol = _panel()
    f = compute_features(close, vol)
    s = make_ranker("consistency").score(f.xs(close.index[-1], level="date"))
    assert len(s) == 6 and s.notna().all()


def test_sue_fcfy_preset_ranks_on_fundamentals_only():
    assert BLENDS["sue_fcfy"] == {"sue": 0.5, "fcf_yield": 0.5}
    r = make_ranker("sue_fcfy")
    assert isinstance(r, BlendRanker) and not r.needs_training
