import pandas as pd
import pytest

from src.portfolio import Rules, State, drift_weights, rebalance, size_positions

T0 = pd.Timestamp("2024-01-02")


def _scores(d):
    return pd.Series(d, dtype=float)


def test_enters_top_n_and_respects_cap_and_cash():
    rules = Rules(top_n=3, sizing="equal", max_weight=0.5, cash_buffer=0.1)
    s = _scores({"A": 5, "B": 4, "C": 3, "D": 2, "E": 1})
    w, trades, st = rebalance(s, None, rules, State(), T0)
    assert set(w.index) == {"A", "B", "C"}
    assert w.sum() == pytest.approx(0.9)
    assert (w <= 0.5 + 1e-9).all()
    assert (trades > 0).all()


def test_exits_when_dropped_from_ranking():
    rules = Rules(top_n=2, sizing="equal", max_weight=1.0, cash_buffer=0.0)
    st = State(weights=pd.Series({"A": 0.5, "B": 0.5}))
    s = _scores({"A": 5, "C": 4, "B": 1})          # B falls out, C enters
    w, trades, st2 = rebalance(s, None, rules, st, T0)
    assert "B" not in w.index and trades["B"] == pytest.approx(-0.5)
    assert w["C"] == pytest.approx(0.5)
    assert st2.last_exit["B"] == T0


def test_hold_inside_band_and_trade_outside():
    rules = Rules(top_n=2, sizing="equal", max_weight=1.0, cash_buffer=0.0, min_trade_pct=0.2)
    s = _scores({"A": 2, "B": 1})
    # target is 0.5 each; A drifted to 0.55 (10% drift) -> hold; B to 0.3 (40%) -> add
    st = State(weights=pd.Series({"A": 0.55, "B": 0.30}))
    w, trades, _ = rebalance(s, None, rules, st, T0)
    assert w["A"] == pytest.approx(0.55)
    assert "A" not in trades.index
    # B wants +0.20 but only 0.15 of budget is free (A holds 0.55): buy is scaled
    assert trades["B"] == pytest.approx(0.15)
    assert w.sum() == pytest.approx(1.0)


def test_rank_sizing_adds_as_rank_improves_and_trims_as_it_falls():
    rules = Rules(top_n=3, sizing="rank", max_weight=1.0, cash_buffer=0.0, min_trade_pct=0.0)
    s1 = _scores({"A": 3, "B": 2, "C": 1})
    w1, _, st = rebalance(s1, None, rules, State(), T0)
    assert w1["A"] > w1["B"] > w1["C"]
    # C "goes up": now best ranked -> bigger target -> buy; A falls -> trim
    s2 = _scores({"C": 3, "B": 2, "A": 1})
    w2, trades, _ = rebalance(s2, None, rules, st, T0 + pd.Timedelta(days=1))
    assert trades["C"] > 0 and trades["A"] < 0
    assert w2["C"] == pytest.approx(w1["A"])


def test_reentry_cooldown_blocks_immediate_rebuy():
    rules = Rules(top_n=1, sizing="equal", max_weight=1.0, cash_buffer=0.0, reentry_cooldown_days=5)
    st = State(weights=pd.Series({"A": 1.0}))
    _, _, st = rebalance(_scores({"B": 2, "A": 1}), None, rules, st, T0)       # exit A
    w, _, _ = rebalance(_scores({"A": 2, "B": 1}), None, rules, st, T0 + pd.Timedelta(days=2))
    assert "A" not in w.index and "B" in w.index                               # still blocked
    w, _, _ = rebalance(_scores({"A": 2, "B": 1}), None, rules, st, T0 + pd.Timedelta(days=6))
    assert "A" in w.index                                                      # cooldown over


def test_inverse_vol_favours_low_vol():
    rules = Rules(top_n=2, sizing="inverse_vol", max_weight=1.0, cash_buffer=0.0)
    w = size_positions(_scores({"A": 1, "B": 1}), pd.Series({"A": 0.10, "B": 0.40}), rules)
    assert w["A"] == pytest.approx(0.8) and w["B"] == pytest.approx(0.2)


def test_drift_weights_sums_consistently():
    w = pd.Series({"A": 0.5, "B": 0.3})       # 20% cash
    r = pd.Series({"A": 0.10, "B": -0.10})
    d = drift_weights(w, r)
    # portfolio grew by 0.5*0.1 - 0.3*0.1 = +2%
    assert d["A"] == pytest.approx(0.55 / 1.02)
    assert d["B"] == pytest.approx(0.27 / 1.02)


def test_equal_sector_mode_takes_best_per_sector_then_fills_from_ranking():
    sectors = {"A": "Tech", "B": "Tech", "C": "Tech", "D": "Energy", "E": "Energy", "F": "Health", "G": "Health", "U": "Unknown"}
    rules = Rules(top_n=5, sizing="equal", max_weight=1.0, cash_buffer=0.0, sector_mode="equal", sectors=sectors)
    s = _scores({"A": 9, "B": 8, "C": 7, "U": 6.5, "D": 6, "E": 5, "F": 4, "G": 3})
    w, trades, st = rebalance(s, None, rules, State(), T0)
    # 5 // 3 sectors = 1 slot each -> A, D, F; the 2 leftover slots go to the best
    # remaining names overall: B (8) and C (7). U (6.5, no sector) just misses.
    assert set(w.index) == {"A", "D", "F", "B", "C"}


def test_equal_sector_mode_without_sector_map_falls_back_to_top_n():
    rules = Rules(top_n=2, sizing="equal", max_weight=1.0, cash_buffer=0.0, sector_mode="equal", sectors=None)
    s = _scores({"A": 3, "B": 2, "C": 1})
    w, _, _ = rebalance(s, None, rules, State(), T0)
    assert set(w.index) == {"A", "B"}


def test_unknown_sector_mode_raises():
    rules = Rules(top_n=2, sizing="equal", max_weight=1.0, cash_buffer=0.0, sector_mode="bogus", sectors={"A": "X"})
    with pytest.raises(ValueError):
        rebalance(_scores({"A": 3, "B": 2}), None, rules, State(), T0)


def test_cap_sector_mode_limits_names_per_sector_and_keeps_rank_order():
    sectors = {"A": "Tech", "B": "Tech", "C": "Tech", "D": "Energy", "E": "Energy", "F": "Health", "G": "Health"}
    # top_n 4, cap 0.5 -> at most 2 names per sector; U1/U2/U3 have no sector and share one "Unknown" bucket
    rules = Rules(top_n=4, sizing="equal", max_weight=1.0, cash_buffer=0.0, sector_mode="cap", sector_cap=0.5, sectors=sectors)
    s = _scores({"A": 9, "B": 8, "C": 7, "U1": 6.5, "U2": 6.4, "U3": 6.3, "D": 6, "E": 5, "F": 4, "G": 3})
    w, _, _ = rebalance(s, None, rules, State(), T0)
    # A, B fill Tech; C is skipped; U1, U2 fill the Unknown bucket and the book is full
    assert set(w.index) == {"A", "B", "U1", "U2"}
    # a cap below one slot still allows one name per sector
    tight = Rules(top_n=3, sizing="equal", max_weight=1.0, cash_buffer=0.0, sector_mode="cap", sector_cap=0.1, sectors=sectors)
    w, _, _ = rebalance(s, None, tight, State(), T0)
    assert set(w.index) == {"A", "U1", "D"}


def test_cap_sector_mode_needs_a_valid_cap_and_falls_back_without_a_sector_map():
    bad = Rules(top_n=2, sizing="equal", max_weight=1.0, cash_buffer=0.0, sector_mode="cap", sectors={"A": "X"})
    with pytest.raises(ValueError):
        rebalance(_scores({"A": 3, "B": 2}), None, bad, State(), T0)
    no_map = Rules(top_n=2, sizing="equal", max_weight=1.0, cash_buffer=0.0, sector_mode="cap", sector_cap=0.5, sectors=None)
    w, _, _ = rebalance(_scores({"A": 3, "B": 2, "C": 1}), None, no_map, State(), T0)
    assert set(w.index) == {"A", "B"}
