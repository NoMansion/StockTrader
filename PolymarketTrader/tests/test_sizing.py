import pytest

from src.sizing import Exposure, SizingRules, exit_signal, expected_return, kelly_fraction, plan_entry, shrink

RULES = SizingRules(shrink_weight=0.5, kelly_fraction=0.25, min_edge=0.04, max_disagreement=0.30, min_price=0.08,
                    max_price=0.92, max_position_pct=0.03, max_event_pct=0.06, max_category_pct=0.25,
                    max_total_exposure_pct=0.50, min_order_usd=5.0, max_order_usd=100.0)


def exp(equity=1000.0, cash=1000.0, **kw):
    return Exposure(equity=equity, cash=cash, **kw)


def test_shrink_moves_part_way_and_clamps():
    assert shrink(0.70, 0.50, 0.5) == pytest.approx(0.60)
    assert shrink(0.70, 0.50, 0.0) == pytest.approx(0.50)
    assert shrink(0.70, 0.50, 1.0) == pytest.approx(0.70)
    assert shrink(0.70, 0.50, 5.0) == pytest.approx(0.70)      # weight is clamped to [0, 1]


def test_kelly_matches_the_textbook_formula():
    # even-money bet won 60% of the time: Kelly = 2p - 1 = 0.20
    assert kelly_fraction(0.60, 0.50) == pytest.approx(0.20)
    assert kelly_fraction(0.40, 0.50) == 0.0
    assert kelly_fraction(0.60, 1.0) == 0.0
    assert expected_return(0.60, 0.50) == pytest.approx(0.20)


def test_buys_yes_when_model_is_above_the_market():
    sz = plan_entry(0.70, 0.50, ask_yes=0.51, ask_no=0.51, exposure=exp(), rules=RULES)
    assert sz.trade and sz.side == "YES"
    assert sz.q == pytest.approx(0.60)
    assert sz.edge == pytest.approx(0.09)
    # quarter Kelly = 0.25 * 0.09/0.49 * 1000 = 45.9, but the 3% market cap binds at $30
    assert sz.stake == pytest.approx(30.0)
    assert sz.binding == "market cap"
    assert sz.limit_price == pytest.approx(0.56)


def test_buys_no_when_model_is_below_the_market():
    sz = plan_entry(0.30, 0.50, ask_yes=0.51, ask_no=0.51, exposure=exp(), rules=RULES)
    assert sz.trade and sz.side == "NO"
    assert sz.q == pytest.approx(0.60)


def test_no_trade_when_edge_is_under_the_threshold():
    sz = plan_entry(0.56, 0.50, ask_yes=0.51, ask_no=0.51, exposure=exp(), rules=RULES)
    assert not sz.trade and "edge" in sz.reason


def test_fee_eats_the_edge():
    # q = 0.56 shrunk from 0.62; cost 0.51 + 0.024 fee leaves 0.026 < 0.04
    sz = plan_entry(0.62, 0.50, ask_yes=0.51, ask_no=0.51, exposure=exp(), rules=RULES, fee_yes=0.024, fee_no=0.024)
    assert not sz.trade
    free = plan_entry(0.62, 0.50, ask_yes=0.51, ask_no=0.51, exposure=exp(), rules=RULES)
    assert free.trade


def test_large_disagreement_is_refused_not_bet():
    sz = plan_entry(0.95, 0.50, ask_yes=0.51, ask_no=0.51, exposure=exp(), rules=RULES)
    assert not sz.trade and "gap" in sz.reason


def test_price_band():
    sz = plan_entry(0.20, 0.05, ask_yes=0.06, ask_no=0.96, exposure=exp(), rules=RULES)
    assert not sz.trade and "outside" in sz.reason


def test_kelly_binds_for_a_small_edge():
    rules = SizingRules(**{**RULES.__dict__, "max_position_pct": 0.5, "max_event_pct": 0.5})
    sz = plan_entry(0.60, 0.50, ask_yes=0.51, ask_no=0.51, exposure=exp(), rules=rules)
    assert sz.trade and sz.binding == "kelly"
    assert sz.stake == pytest.approx(0.25 * (0.55 - 0.51) / 0.49 * 1000, abs=0.01)


def test_caps_use_existing_exposure():
    sz = plan_entry(0.70, 0.50, 0.51, 0.51, exp(market=28.0), RULES)
    assert not sz.trade and "market cap" in sz.reason                       # only $2 of room left
    sz = plan_entry(0.70, 0.50, 0.51, 0.51, exp(event=45.0), RULES)
    assert sz.trade and sz.stake == pytest.approx(15.0) and sz.binding == "event cap"
    sz = plan_entry(0.70, 0.50, 0.51, 0.51, exp(total=497.0), RULES)
    assert not sz.trade and "total exposure cap" in sz.reason
    sz = plan_entry(0.70, 0.50, 0.51, 0.51, exp(cash=12.0), RULES)
    assert sz.trade and sz.stake == pytest.approx(12.0) and sz.binding == "cash"


def test_order_ceiling_holds_whatever_the_equity():
    sz = plan_entry(0.70, 0.50, 0.51, 0.51, exp(equity=1_000_000, cash=1_000_000), RULES)
    assert sz.stake == pytest.approx(100.0) and sz.binding == "order ceiling"


def test_annual_return_hurdle():
    rules = SizingRules(**{**RULES.__dict__, "min_annual_return": 0.5})
    slow = plan_entry(0.70, 0.50, 0.51, 0.51, exp(), rules, days_to_resolution=365)
    fast = plan_entry(0.70, 0.50, 0.51, 0.51, exp(), rules, days_to_resolution=30)
    assert not slow.trade and "a year" in slow.reason
    assert fast.trade


def test_bad_inputs():
    assert not plan_entry(1.2, 0.5, 0.51, 0.51, exp(), RULES).trade
    assert not plan_entry(0.6, 0.0, 0.51, 0.51, exp(), RULES).trade
    assert not plan_entry(0.7, 0.5, None, None, exp(), RULES).trade
    assert not plan_entry(0.7, 0.5, 0.51, 0.51, exp(equity=0), RULES).trade


def test_weight_override_lowers_conviction():
    full = plan_entry(0.70, 0.50, 0.51, 0.51, exp(), RULES)
    low = plan_entry(0.70, 0.50, 0.51, 0.51, exp(), RULES, weight=0.25)
    assert full.trade and low.edge < full.edge


def test_exit_only_when_edge_has_reversed():
    sell, _ = exit_signal("YES", p_model=0.30, p_market=0.60, bid=0.59, rules=RULES)
    assert sell                                    # q = 0.45, bid 0.59
    hold, _ = exit_signal("YES", p_model=0.58, p_market=0.60, bid=0.59, rules=RULES)
    assert not hold                                # q = 0.59
    sell_no, _ = exit_signal("NO", p_model=0.90, p_market=0.60, bid=0.39, rules=RULES)
    assert sell_no                                 # NO q = 0.25, bid 0.39
    assert exit_signal("YES", 0.3, 0.6, None, RULES)[0] is False
