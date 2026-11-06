import numpy as np
import pandas as pd

from src.backtest import BacktestConfig, run_backtest
from src.features import compute_features, forward_excess_return
from src.portfolio import Rules


def test_features_have_no_lookahead(synthetic_prices):
    """Perturbing the future must not change features at t."""
    close, volume = synthetic_prices
    t = close.index[400]
    f1 = compute_features(close, volume).xs(t, level="date")
    close2 = close.copy()
    close2.iloc[401:] *= np.random.default_rng(1).uniform(0.5, 1.5, size=close2.iloc[401:].shape)
    f2 = compute_features(close2, volume).xs(t, level="date")
    pd.testing.assert_frame_equal(f1, f2)


def test_labels_are_forward_looking(synthetic_prices):
    close, _ = synthetic_prices
    y = forward_excess_return(close, 10)
    t = close.index[100]
    expected = close.iloc[110] / close.iloc[100] - 1
    expected = expected - expected.mean()
    pd.testing.assert_series_equal(y.xs(t, level="date").sort_index(), expected.sort_index(), check_names=False)


def test_momentum_backtest_runs_and_finds_trend(synthetic_prices):
    close, volume = synthetic_prices
    rules = Rules(top_n=5, sizing="rank", max_weight=0.3, min_trade_pct=0.2)
    cfg = BacktestConfig(ranker="momentum", slippage_bps=5)
    res = run_backtest(close, volume, rules, cfg)
    s = res.summary()
    assert s["days"] > 250
    assert 0 < s["avg_positions"] <= 5
    assert res.weights.sum(axis=1).max() <= 1.0 + 1e-6
    # synthetic winners are persistent, so momentum should beat the EW benchmark
    assert s["strategy_cagr"] > s["benchmark_cagr"]
    assert s["mean_ic"] > 0


def test_costs_reduce_returns(synthetic_prices):
    close, volume = synthetic_prices
    rules = Rules(top_n=5, sizing="equal", min_trade_pct=0.0)
    free = run_backtest(close, volume, rules, BacktestConfig(slippage_bps=0)).daily["ret"].sum()
    costly = run_backtest(close, volume, rules, BacktestConfig(slippage_bps=50)).daily["ret"].sum()
    assert costly < free
