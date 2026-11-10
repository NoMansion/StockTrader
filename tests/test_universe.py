import numpy as np
import pandas as pd

from src.backtest import BacktestConfig, run_backtest
from src.portfolio import Rules
from src.universe import apply_membership, liquidity_membership


def test_liquidity_membership_is_point_in_time(synthetic_prices):
    close, volume = synthetic_prices
    m = liquidity_membership(close, volume, top_k=10, min_price=5.0, lookback=20)
    assert m.shape == close.shape
    assert (m.sum(axis=1).iloc[30:] == 10).all()           # exactly top_k once warmed up
    # perturbing the future must not change membership at t
    t = close.index[300]
    close2 = close.copy(); close2.iloc[301:] *= 3
    m2 = liquidity_membership(close2, volume, top_k=10, min_price=5.0, lookback=20)
    pd.testing.assert_series_equal(m.loc[t], m2.loc[t])


def test_liquidity_membership_price_floor(synthetic_prices):
    close, volume = synthetic_prices
    close = close.copy(); close["T00"] = 1.0                 # penny stock
    m = liquidity_membership(close, volume, top_k=10, min_price=5.0, lookback=20)
    assert not m["T00"].any()


def test_apply_membership_filters_scores():
    idx = pd.to_datetime(["2024-01-02"])
    m = pd.DataFrame({"A": [True], "B": [False]}, index=idx)
    s = pd.Series({"A": 1.0, "B": 2.0})
    out = apply_membership(s, m, idx[0])
    assert list(out.index) == ["A"]
    assert apply_membership(s, None, idx[0]).equals(s)


def test_backtest_only_holds_members_and_exits_on_removal(synthetic_prices):
    close, volume = synthetic_prices
    # T00..T04 are the planted winners; ban them after day 400 to force exits
    m = pd.DataFrame(True, index=close.index, columns=close.columns)
    m.loc[close.index[400]:, ["T00", "T01", "T02", "T03", "T04"]] = False
    rules = Rules(top_n=5, sizing="rank", max_weight=0.3)
    res = run_backtest(close, volume, rules, BacktestConfig(ranker="momentum"), membership=m)
    w = res.weights.reindex(columns=close.columns).fillna(0.0)
    held_after = w.loc[close.index[401]:, ["T00", "T01", "T02", "T03", "T04"]]
    assert (held_after == 0).all().all()
    assert res.weights.loc[: close.index[399], ["T00", "T01", "T02", "T03", "T04"]].sum().sum() > 0


def test_optimizer_path_also_sells_non_members(synthetic_prices):
    close, volume = synthetic_prices
    m = pd.DataFrame(True, index=close.index, columns=close.columns)
    m.loc[close.index[400]:, ["T00", "T01", "T02", "T03", "T04"]] = False
    rules = Rules(sizing="optimizer", max_weight=0.15)
    res = run_backtest(close, volume, rules, BacktestConfig(ranker="momentum"), membership=m)
    w = res.weights.reindex(columns=close.columns).fillna(0.0)
    held_after = w.loc[close.index[401]:, ["T00", "T01", "T02", "T03", "T04"]]
    assert (held_after == 0).all().all()


def test_liquidity_membership_uses_the_prices_it_is_given():
    """Regression: a serial reverse-splitter has a huge split-adjusted price but a
    sub-dollar raw price. Ranked on raw close x volume it must NOT be a member."""
    idx = pd.date_range("2020-01-01", periods=60, freq="B")
    raw = pd.DataFrame({"GOOD": 50.0, "JUNK": 0.01}, index=idx)
    adj = pd.DataFrame({"GOOD": 50.0, "JUNK": 1e9}, index=idx)   # 1e11x of reverse splits
    vol = pd.DataFrame({"GOOD": 1e6, "JUNK": 1e6}, index=idx)
    m_raw = liquidity_membership(raw, vol, top_k=1, min_price=5.0, lookback=20)
    m_adj = liquidity_membership(adj, vol, top_k=1, min_price=5.0, lookback=20)
    assert bool(m_raw.iloc[-1]["GOOD"]) and not bool(m_raw.iloc[-1]["JUNK"])
    assert bool(m_adj.iloc[-1]["JUNK"])   # this is the bug the dataset loader must avoid


def test_clean_bars_drops_placeholder_prices():
    from src.data import clean_bars
    rows = [
        {"date": "2024-01-02", "ticker": "X", "open": 1, "high": 1, "low": 1, "close": 1.0, "volume": 10, "adj_close": 1.0},
        {"date": "2024-01-03", "ticker": "X", "open": 1, "high": 1, "low": 1, "close": 0.000001, "volume": 0, "adj_close": 0.000001},
    ]
    out = clean_bars(pd.DataFrame(rows))
    assert len(out) == 1 and out["close"].iloc[0] == 1.0
