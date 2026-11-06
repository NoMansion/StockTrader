import numpy as np
import pandas as pd
import pytest

from src.backtest import BacktestConfig, run_backtest
from src.optimizer import OptimizerConfig, allocate, expected_returns, optimize_weights, shrunk_covariance
from src.portfolio import Rules, State, rebalance


def _diag_cov(names, var=0.0002):
    return pd.DataFrame(np.eye(len(names)) * var, index=names, columns=names)


def test_weights_follow_expected_return_and_respect_constraints():
    names = list("ABCDE")
    mu = pd.Series([0.002, 0.001, 0.0005, 0.0, -0.001], index=names)
    cfg = OptimizerConfig(risk_aversion=8, tc_bps=0, max_weight=0.4, cash_buffer=0.0, min_weight=0.0)
    w = optimize_weights(mu, _diag_cov(names), pd.Series(dtype=float), cfg)
    assert w.get("A", 0) >= w.get("B", 0) >= w.get("C", 0)
    assert "E" not in w.index                       # negative mu -> no long position
    assert (w <= 0.4 + 1e-6).all() and w.sum() <= 1.0 + 1e-6


def test_no_signal_means_cash():
    names = list("ABC")
    cfg = OptimizerConfig(tc_bps=0, cash_buffer=0.0)
    w = optimize_weights(pd.Series(0.0, index=names), _diag_cov(names), pd.Series(dtype=float), cfg)
    assert w.empty


def test_transaction_cost_penalty_reduces_turnover():
    names = list("ABCD")
    mu = pd.Series([0.001, 0.001, 0.0009, 0.0009], index=names)
    prev = pd.Series({"C": 0.3, "D": 0.3})
    cheap = optimize_weights(mu, _diag_cov(names), prev, OptimizerConfig(tc_bps=0, cash_buffer=0, min_weight=0))
    costly = optimize_weights(mu, _diag_cov(names), prev, OptimizerConfig(tc_bps=100, cash_buffer=0, min_weight=0))
    turn = lambda w: (w.reindex(names).fillna(0) - prev.reindex(names).fillna(0)).abs().sum()
    assert turn(costly) < turn(cheap)


def test_exposure_and_count_are_decided_by_signal_strength():
    """The model's measured edge (IC) drives both how much to invest and how
    many names: strong edge -> fully invested and concentrated at the cap;
    weak edge -> more cash, spread thinner; no edge -> all cash."""
    rng = np.random.default_rng(3)
    names = [f"T{i}" for i in range(40)]
    rets = pd.DataFrame(rng.normal(0, 0.015, (120, 40)), columns=names)
    scores = pd.Series(rng.normal(size=40), index=names)
    cfg = OptimizerConfig(tc_bps=0, cash_buffer=0.02, min_weight=0.005, max_weight=0.10)
    strong = allocate(scores, rets, pd.Series(dtype=float), ic=0.10, cfg=cfg)
    weak = allocate(scores, rets, pd.Series(dtype=float), ic=0.01, cfg=cfg)
    none = allocate(scores, rets, pd.Series(dtype=float), ic=0.0, cfg=cfg)
    assert strong.sum() == pytest.approx(0.98, abs=1e-3)   # fully invested
    assert int(((strong - 0.10).abs() < 1e-3).sum()) >= 8     # concentrated at cap
    assert weak.sum() < strong.sum()                       # weak edge -> more cash
    assert len(weak) != len(strong) and len(weak) > 0      # count is not fixed
    assert none.empty                                      # IC at floor -> cash


def test_max_positions_cap_is_optional():
    rng = np.random.default_rng(4)
    names = [f"T{i}" for i in range(30)]
    rets = pd.DataFrame(rng.normal(0, 0.015, (120, 30)), columns=names)
    scores = pd.Series(rng.normal(size=30), index=names)
    capped = allocate(scores, rets, pd.Series(dtype=float), ic=0.1, cfg=OptimizerConfig(tc_bps=0, max_positions=5))
    assert len(capped) <= 5


def test_expected_returns_scale_with_ic_and_vol():
    scores = pd.Series({"A": 2.0, "B": 0.0, "C": -2.0})
    vol = pd.Series({"A": 0.01, "B": 0.01, "C": 0.02})
    cfg = OptimizerConfig()
    mu = expected_returns(scores, vol, ic=0.05, cfg=cfg)
    assert mu["A"] > 0 > mu["C"] and abs(mu["B"]) < 1e-12
    assert abs(mu["C"]) == pytest.approx(2 * mu["A"])   # C has 2x vol


def test_shrinkage_moves_toward_diagonal():
    rng = np.random.default_rng(5)
    f = rng.normal(size=(200, 1))
    r = pd.DataFrame(f @ np.ones((1, 3)) * 0.01 + rng.normal(0, 0.005, (200, 3)), columns=list("ABC"))
    full = shrunk_covariance(r, 0.0)
    half = shrunk_covariance(r, 0.5)
    assert abs(half.loc["A", "B"]) == pytest.approx(0.5 * abs(full.loc["A", "B"]), rel=1e-6)


def test_rebalance_optimizer_path_records_exits():
    names = list("ABCD")
    rng = np.random.default_rng(6)
    rets = pd.DataFrame(rng.normal(0, 0.015, (120, 4)), columns=names)
    rules = Rules(sizing="optimizer", optimizer=OptimizerConfig(tc_bps=0, cash_buffer=0.0, min_weight=0.0))
    st = State(weights=pd.Series({"D": 0.5}))
    scores = pd.Series({"A": 2.0, "B": 1.0, "C": -1.0, "D": -2.0})
    w, trades, st2 = rebalance(scores, None, rules, st, pd.Timestamp("2024-01-02"), returns_window=rets, ic=0.1)
    assert "D" not in w.index and trades["D"] == pytest.approx(-0.5)
    assert "D" in st2.last_exit


def test_backtest_runs_with_optimizer_and_count_varies(synthetic_prices):
    close, volume = synthetic_prices
    rules = Rules(sizing="optimizer", max_weight=0.15, optimizer=OptimizerConfig(max_weight=0.15, tc_bps=20))
    res = run_backtest(close, volume, rules, BacktestConfig(ranker="momentum"))
    s = res.summary()
    assert s["days"] > 250
    assert res.weights.sum(axis=1).max() <= 1.0 + 1e-6
    assert res.daily["n_pos"].nunique() > 1              # count is decided day by day
    assert s["strategy_cagr"] > s["benchmark_cagr"]
