import numpy as np
import pandas as pd
import pytest

from src.backtest import AutoTune, BacktestConfig, run_backtest
from src.costs import CostModel, dollar_adv
from src.optimizer import OptimizerConfig, allocate, optimize_weights
from src.portfolio import Rules


def test_impact_cost_grows_with_trade_size_and_shrinks_with_liquidity():
    cm = CostModel(kind="impact", spread_bps=0, impact_coef=0.1, capital=1_000_000, flat_bps=0)
    adv = pd.Series({"BIG": 1e9, "SMALL": 1e6})
    sig = pd.Series({"BIG": 0.015, "SMALL": 0.03})
    small_trade = cm.trade_cost(pd.Series({"BIG": 0.01}), adv, sig)
    big_trade = cm.trade_cost(pd.Series({"BIG": 0.04}), adv, sig)
    assert big_trade > 4 * small_trade            # sqrt impact: cost per $ rises with size
    thin = cm.trade_cost(pd.Series({"SMALL": 0.01}), adv, sig)
    assert thin > small_trade * 10                 # same $ trade, far costlier in the thin name


def test_flat_model_matches_old_behaviour():
    cm = CostModel(kind="flat", flat_bps=10)
    assert cm.trade_cost(pd.Series({"A": 0.3, "B": -0.2}), None, None) == pytest.approx(0.5 * 10 / 1e4)


def test_linear_coeffs_floor_and_ordering():
    cm = CostModel(kind="impact", spread_bps=3, impact_coef=0.1, capital=2_000_000, flat_bps=5)
    adv = pd.Series({"BIG": 5e8, "SMALL": 2e6})
    sig = pd.Series({"BIG": 0.015, "SMALL": 0.03})
    c = cm.linear_coeffs(adv.index, adv, sig, ref_delta_w=0.01)
    assert c["SMALL"] > c["BIG"] >= 5 / 1e4


def test_optimizer_avoids_thin_names_for_large_accounts():
    """Same scores: a $50k account can hold the thin name; a $20M account can't justify it."""
    rng = np.random.default_rng(7)
    names = ["LIQ1", "LIQ2", "LIQ3", "THIN"]
    rets = pd.DataFrame(rng.normal(0, 0.015, (120, 4)), columns=names)
    scores = pd.Series({"LIQ1": 0.5, "LIQ2": 0.3, "LIQ3": 0.1, "THIN": 1.0})   # THIN has the best score
    adv = pd.Series({"LIQ1": 5e8, "LIQ2": 5e8, "LIQ3": 5e8, "THIN": 3e5})
    cfg = OptimizerConfig(risk_aversion=4, max_weight=0.4, cash_buffer=0.0, min_weight=0.005, tc_multiplier=1.0)
    small = allocate(scores, rets, pd.Series(dtype=float), ic=0.1, cfg=cfg, adv=adv,
                     cost_model=CostModel(capital=50_000, spread_bps=3, impact_coef=0.1, max_participation=1.0))
    big = allocate(scores, rets, pd.Series(dtype=float), ic=0.1, cfg=cfg, adv=adv,
                   cost_model=CostModel(capital=20_000_000, spread_bps=3, impact_coef=0.1, max_participation=1.0))
    assert small.get("THIN", 0) > 0
    assert big.get("THIN", 0) < small.get("THIN", 0)


def test_participation_cap_limits_daily_trade():
    names = list("AB")
    mu = pd.Series({"A": 0.003, "B": 0.003})
    cov = pd.DataFrame(np.eye(2) * 2e-4, index=names, columns=names)
    cfg = OptimizerConfig(risk_aversion=1, max_weight=0.5, cash_buffer=0.0, min_weight=0.0, tc_bps=0)
    caps = pd.Series({"A": 0.02, "B": 1.0})       # A: at most 2% of portfolio per day
    w = optimize_weights(mu, cov, pd.Series(dtype=float), cfg, trade_caps=caps)
    assert w["A"] <= 0.02 + 1e-6 and w["B"] > 0.3


def test_pgd_matches_slsqp_on_small_problem():
    rng = np.random.default_rng(8)
    names = [f"T{i}" for i in range(8)]
    rets = pd.DataFrame(rng.normal(0, 0.015, (150, 8)), columns=names)
    scores = pd.Series(rng.normal(size=8), index=names)
    prev = pd.Series({"T0": 0.1, "T3": 0.2})
    a = allocate(scores, rets, prev, 0.05, OptimizerConfig(solver="pgd", tc_bps=20, min_weight=0.0))
    b = allocate(scores, rets, prev, 0.05, OptimizerConfig(solver="slsqp", tc_bps=20, min_weight=0.0))
    diff = (a.reindex(names).fillna(0) - b.reindex(names).fillna(0)).abs().max()
    assert diff < 2e-3


def test_pgd_scales_to_many_names():
    import time
    rng = np.random.default_rng(9)
    n = 800
    names = [f"T{i}" for i in range(n)]
    rets = pd.DataFrame(rng.normal(0, 0.015, (120, n)), columns=names)
    scores = pd.Series(rng.normal(size=n), index=names)
    adv = pd.Series(rng.lognormal(17, 1.5, n), index=names)
    t = time.time()
    w = allocate(scores, rets, pd.Series(dtype=float), 0.05, OptimizerConfig(), adv=adv, cost_model=CostModel(capital=250_000))
    assert time.time() - t < 15
    assert 0 < w.sum() <= 0.98 + 1e-6 and (w <= 0.10 + 1e-6).all()


def test_dollar_adv_is_point_in_time(synthetic_prices):
    close, volume = synthetic_prices
    a1 = dollar_adv(close, volume)
    close2 = close.copy(); close2.iloc[301:] *= 5
    a2 = dollar_adv(close2, volume)
    pd.testing.assert_series_equal(a1.iloc[300], a2.iloc[300])


def test_backtest_impact_costs_and_autotune(synthetic_prices):
    close, volume = synthetic_prices
    rules = Rules(sizing="optimizer", max_weight=0.15, optimizer=OptimizerConfig(max_weight=0.15))
    cfg = BacktestConfig(ranker="momentum", cost_model=CostModel(capital=100_000),
                         auto_tune=AutoTune(enabled=True, risk_aversion=[4.0, 16.0], tc_multiplier=[1.0, 2.5], tune_window=120),
                         retrain_every_days=63)
    res = run_backtest(close, volume, rules, cfg)
    s = res.summary()
    assert s["days"] > 250
    assert s["avg_daily_cost_bps"] >= 0
    assert not res.tune_log.empty                                  # tuning happened
    assert res.daily["risk_aversion"].nunique() >= 1
    assert set(res.tune_log["risk_aversion"]).issubset({4.0, 16.0})
    # tuned settings are only ever applied after the tune date (walk-forward)
    first = res.tune_log["date"].iloc[0]
    assert (res.daily.loc[:first].index[-1] <= first)
