import numpy as np
import pandas as pd
import pytest

from src.backtest import BacktestConfig, BacktestResult, run_backtest
from src.books import Book, book_rules, build_books, combine_results, combine_weights, run_books, single_book
from src.portfolio import Rules


def _cfg(books):
    return {"model": {"type": "novol", "weights": None}, "portfolio": {"books": books}}


def test_build_books_validates_weights_and_names():
    assert build_books(_cfg(None)) is None
    bks = build_books(_cfg([{"name": "mom", "ranker": "novol", "weight": 0.7}, {"name": "earn", "ranker": "earnings", "weight": 0.3, "top_n": 40}]))
    assert [b.name for b in bks] == ["mom", "earn"] and bks[1].top_n == 40
    with pytest.raises(ValueError):
        build_books(_cfg([{"name": "a", "ranker": "novol", "weight": 0.6}, {"name": "b", "ranker": "novol", "weight": 0.6}]))
    with pytest.raises(ValueError):
        build_books(_cfg([{"name": "a", "ranker": "novol", "weight": 0.5}, {"name": "a", "ranker": "novol", "weight": 0.5}]))
    assert single_book(_cfg(None)) == Book("main", "novol", 1.0)


def test_book_rules_split_the_invested_budget():
    rules = Rules(top_n=55, cash_buffer=0.02)
    r = book_rules(rules, Book("earn", "earnings", 0.3, top_n=40))
    assert r.top_n == 40 and r.cash_buffer == pytest.approx(1 - 0.3 * 0.98)
    r2 = book_rules(rules, Book("mom", "novol", 0.7))
    assert (1 - r.cash_buffer) + (1 - r2.cash_buffer) == pytest.approx(0.98)   # together: the usual budget


def test_combine_weights_adds_overlaps():
    w = combine_weights({"a": pd.Series({"X": 0.1, "Y": 0.2}), "b": pd.Series({"Y": 0.05, "Z": 0.3})})
    assert w.to_dict() == pytest.approx({"Z": 0.3, "Y": 0.25, "X": 0.1}) and list(w.index) == ["Z", "Y", "X"]


def _fake_result(ret, idx, cols):
    daily = pd.DataFrame({"ret": ret, "bench_ret": 0.001, "turnover": 0.01, "cost": 0.0001, "n_pos": 10, "ic": 0.02}, index=idx)
    w = pd.DataFrame(0.05, index=idx, columns=cols)
    tr = pd.DataFrame({"date": [idx[0]], "ticker": [cols[0]], "delta_w": [0.05]})
    return BacktestResult(daily=daily, weights=w, trades=tr)


def test_combine_results_sums_books():
    idx = pd.bdate_range("2024-01-01", periods=5)
    r = combine_results({"a": _fake_result(0.01, idx, ["X", "Y"]), "b": _fake_result(0.02, idx, ["Y", "Z"])})
    assert np.allclose(r.daily["ret"], 0.03)
    assert np.allclose(r.daily["turnover"], 0.02) and (r.daily["n_pos"] == 20).all() and np.allclose(r.daily["bench_ret"], 0.001)
    assert r.weights.loc[idx[0], "Y"] == pytest.approx(0.10) and r.weights.loc[idx[0], "X"] == pytest.approx(0.05)
    assert list(r.trades["book"]) == ["a", "b"] and "ret_a" in r.daily.columns


def _prices(n_days=420, n=25, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=n_days)
    cols = [f"T{i:02d}" for i in range(n)]
    drift = rng.normal(0.0004, 0.0006, n)
    close = pd.DataFrame(np.exp(np.cumsum(rng.normal(drift, 0.015, (n_days, n)), axis=0)) * 50, index=idx, columns=cols)
    volume = pd.DataFrame(rng.integers(1e5, 1e6, (n_days, n)), index=idx, columns=cols)
    return close, volume


def test_run_books_matches_single_book_when_one_book_has_all_the_weight():
    close, volume = _prices()
    rules = Rules(top_n=8, sizing="equal", cash_buffer=0.02)
    cfg = BacktestConfig(ranker="momentum", warmup_days=270, cost_model=__import__("src.costs", fromlist=["CostModel"]).CostModel(kind="flat", flat_bps=10))
    single = run_backtest(close, volume, rules, cfg)
    one = run_books(close, volume, rules, cfg, [Book("only", "momentum", 1.0)])
    assert np.allclose(single.daily["ret"].fillna(0), one.daily["ret"].fillna(0))
    two = run_books(close, volume, rules, cfg, [Book("m", "momentum", 0.5), Book("n", "novol", 0.5, top_n=5)])
    inv = two.weights.sum(axis=1)
    assert inv.iloc[-1] <= 0.98 + 1e-6 and inv.iloc[-1] > 0.9                   # together they invest the usual budget
    assert set(two.trades["book"]) == {"m", "n"} and {"ret_m", "ret_n"} <= set(two.daily.columns)
