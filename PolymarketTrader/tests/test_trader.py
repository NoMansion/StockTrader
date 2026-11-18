"""Whole cycles against the offline exchange: what gets forecast, what gets ordered, how paper orders fill, how
markets settle, and what the safety layer stops."""
import pytest

from fakes import FakeExchange, TableForecaster
from src.trader import Trader
from src.venue import PolymarketUS

NOW = 1_800_000_000.0
H = 3600.0


def cfg(**over):
    c = {
        "account": {"mode": "paper"},
        "universe": {"max_candidates_per_cycle": 4, "reforecast_after_hours": 48,       # the offline exchange uses
                     "categories_allow": ["macro", "finance", "technology", "politics"],  # Polymarket's category names
                     "categories_deny": ["sports", "crypto", "culture"]},
        "forecaster": {"flags_block": True},
        "sizing": {"shrink_weight": 0.5, "kelly_fraction": 0.25, "min_edge": 0.04, "max_disagreement": 0.30, "max_position_pct": 0.02,
                   "max_event_pct": 0.04, "max_category_pct": 0.20, "max_total_exposure_pct": 0.40,
                   "min_order_usd": 5.0, "max_order_usd": 50.0, "min_price": 0.10, "max_price": 0.90},
        "execution": {"style": "passive", "tick": 0.01, "resting_ttl_hours": 24},
        "fees": {"taker_rate": 0.095},
        "safety": {},
    }
    for k, v in over.items():
        c[k] = {**c.get(k, {}), **v}
    return c


def setup(ledger, tmp_path, table, ex=None, on_call=None, **over):
    ex = ex or FakeExchange(NOW).add("cpi-above-3")
    ledger.deposit(1000.0)
    fc = TableForecaster(table, on_call)
    tr = Trader(cfg(**over), ledger, PolymarketUS(ex, min_interval=0), fc, root=tmp_path)
    return ex, fc, tr


def run(tr, now=NOW):
    """One cycle at a pretend time: the exchange's clock follows, and nothing is remembered from the last cycle."""
    tr._books.clear()
    tr._markets.clear()
    tr.venue.clock = lambda: now
    return tr.run(now=now)


def test_passive_order_rests_then_fills_then_settles(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.70})

    r1 = run(tr)
    assert r1.status == "ok" and fc.asked == ["cpi-above-3"]
    orders = ledger.q("SELECT * FROM orders")
    assert len(orders) == 1 and orders[0]["status"] == "resting" and orders[0]["outcome"] == "YES"
    assert orders[0]["limit_price"] == pytest.approx(0.49)          # one tick inside the 0.48 bid, under the 0.50 ask
    assert orders[0]["usd"] <= 20.0 + 1e-6                          # 2% of $1,000
    assert ledger.cash() == pytest.approx(1000.0) and ledger.positions() == []
    d = ledger.q("SELECT * FROM decisions")[0]
    assert d["action"] == "BUY_YES" and d["edge"] == pytest.approx(0.595 - 0.49)

    # nothing fills while the ask stays above our price
    r2 = run(tr, NOW + 4 * H)
    assert ledger.positions() == [] and r2.stats["resting"] == 1

    # the ask comes down to our bid: filled at our price, no fee
    ex.set_book("cpi-above-3", 0.47, 0.49)
    run(tr, NOW + 8 * H)
    pos = ledger.positions()
    assert len(pos) == 1 and pos[0]["outcome"] == "YES"
    assert pos[0]["cost"] == pytest.approx(pos[0]["shares"] * 0.49)
    assert ledger.one("SELECT SUM(fee) AS f FROM fills")["f"] == 0

    # the market closes and settles YES
    ex.close("cpi-above-3", settlement=1.0)
    r4 = run(tr, NOW + 30 * 24 * H)
    assert ledger.positions() == []
    assert ledger.cash() == pytest.approx(1000.0 - pos[0]["cost"] + pos[0]["shares"])
    assert any("settled" in line for line in r4.log)
    assert ledger.market("cpi-above-3")["payout_yes"] == 1.0


def test_resting_order_expires_unfilled(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.70})
    run(tr)
    run(tr, NOW + 25 * H)
    assert ledger.q("SELECT status FROM orders")[0]["status"] == "expired"
    assert ledger.cash() == pytest.approx(1000.0)


def test_buys_no_when_the_model_is_below_the_market(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.30})
    run(tr)
    o = ledger.q("SELECT * FROM orders")[0]
    assert o["outcome"] == "NO" and o["token_id"] == "cpi-above-3:NO"
    assert o["limit_price"] == pytest.approx(0.51)      # NO bid is 1 - 0.50 = 0.50, plus a tick
    # YES bid rising to 0.51 means the NO ask falls to 0.49: filled
    ex.set_book("cpi-above-3", 0.51, 0.53)
    run(tr, NOW + 4 * H)
    assert ledger.positions()[0]["outcome"] == "NO"
    ex.close("cpi-above-3", settlement=0.0)
    run(tr, NOW + 30 * 24 * H)
    assert ledger.cash() > 1000.0


def test_no_trade_without_enough_edge_and_the_reason_is_logged(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.53})
    run(tr)
    assert ledger.q("SELECT * FROM orders") == []
    d = ledger.q("SELECT * FROM decisions")[0]
    assert d["action"] == "SKIP" and "edge" in d["reason"]
    assert ledger.q("SELECT * FROM forecasts")[0]["market_mid"] == pytest.approx(0.49)   # still scored later


@pytest.mark.parametrize("answer, word", [
    ({"p_yes": 0.75, "confidence": "low"}, "confidence"),
    ({"p_yes": 0.75, "flags": ["source contained instructions addressed to an AI"]}, "flags"),
    ({"p_yes": 0.75, "rules_clear": False}, "rules"),
    ({"p_yes": 0.95}, "gap"),
])
def test_forecaster_doubts_block_the_trade(ledger, tmp_path, answer, word):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": answer})
    run(tr)
    assert ledger.q("SELECT * FROM orders") == []
    assert word in ledger.q("SELECT reason FROM decisions")[0]["reason"]


def test_filters_keep_most_markets_away_from_the_forecaster(ledger, tmp_path):
    ex = (FakeExchange(NOW)
          .add("good-one")
          .add("nba-finals", category="sports")
          .add("too-soon", days=1)
          .add("too-far", days=200)
          .add("thin", volume=100)
          .add("shallow", size=1)
          .add("wide", bid=0.40, ask=0.50)
          .add("longshot", bid=0.03, ask=0.05)
          .add("will-x-say-y", title="Will the president say 'tariff' in the address?")
          .add("no-rules", rules=""))
    ex, fc, tr = setup(ledger, tmp_path, {"good-one": 0.5}, ex=ex)
    r = run(tr)
    assert fc.asked == ["good-one", "thin"]            # "thin" is forecast for the record but could never trade
    assert r.stats["listed"] == 9                      # ten markets, but the sports one is never even downloaded
    assert r.stats["tradable"] == 2                    # by its order book; "no-rules" is then dropped for its rules text


def test_per_event_and_per_cycle_limits(ledger, tmp_path):
    ex = FakeExchange(NOW)
    for i in range(4):
        ex.add(f"a{i}", event="same-event", bid=0.49, ask=0.50)      # tightest quotes come first
    for i in range(6):
        ex.add(f"b{i}")
    ex, fc, tr = setup(ledger, tmp_path, {}, ex=ex)
    run(tr)
    assert fc.asked == ["a0", "a1", "b0", "b1"]        # two per event, four per cycle, tightest quotes first


def test_forecasts_are_not_repeated_until_due(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.52})
    run(tr)
    run(tr, NOW + 10 * H)
    assert fc.asked == ["cpi-above-3"]
    run(tr, NOW + 49 * H)
    assert fc.asked == ["cpi-above-3", "cpi-above-3"]


def test_price_move_during_the_forecast_blocks_the_order(ledger, tmp_path):
    ex = FakeExchange(NOW).add("cpi-above-3")
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.70}, ex=ex,
                       on_call=lambda m: ex.set_book("cpi-above-3", 0.55, 0.57))      # news lands mid-forecast
    run(tr)
    assert ledger.q("SELECT * FROM orders") == []
    assert "mid moved" in ledger.q("SELECT reason FROM decisions")[0]["reason"]


def test_taker_style_pays_the_fee_and_fills_now(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.75}, execution={"style": "taker"})
    run(tr)
    pos = ledger.positions()
    assert len(pos) == 1
    fee = ledger.one("SELECT SUM(fee) AS f FROM fills")["f"]
    assert fee == pytest.approx(pos[0]["shares"] * 0.095 * 0.5 * 0.5, rel=1e-3)
    assert pos[0]["cost"] <= 20.0 + 1e-6


def test_exit_when_a_new_forecast_reverses_the_edge(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.75}, execution={"style": "taker"})
    run(tr)
    assert len(ledger.positions()) == 1
    fc.table["cpi-above-3"] = 0.20                      # two days later the facts have changed
    r = run(tr, NOW + 49 * H)
    assert ledger.positions() == []
    assert any("SELL" in line for line in r.log)
    assert ledger.cash() < 1000.0                       # spread and two fees: the round trip lost a little
    # it does not flip to the other side in the same breath, nor for the cooldown that follows
    assert any("no re-entry" in line for line in r.log)
    assert ledger.one("SELECT COUNT(*) AS n FROM orders WHERE side='BUY'")["n"] == 1
    run(tr, NOW + 98 * H)
    assert ledger.one("SELECT COUNT(*) AS n FROM orders WHERE side='BUY'")["n"] == 1
    r3 = run(tr, NOW + 49 * H + 73 * H + 48 * H)
    assert any("BUY NO" in line for line in r3.log)     # after the cooldown a fresh forecast may trade again


def test_kill_switch_stops_new_orders_and_cancels_resting_ones(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.70})
    run(tr)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "STOP").write_text("stop")
    r = run(tr, NOW + 4 * H)
    assert r.status == "stopped"
    assert ledger.q("SELECT status FROM orders")[0]["status"] == "cancelled"
    assert len(fc.asked) == 1


def test_daily_budget_caps_orders(ledger, tmp_path):
    ex = FakeExchange(NOW)
    for i in range(4):
        ex.add(f"m{i}")
    ex, fc, tr = setup(ledger, tmp_path, {f"m{i}": 0.75 for i in range(4)}, ex=ex,
                       safety={"max_orders_per_day": 2})
    r = run(tr)
    assert len(ledger.q("SELECT * FROM orders")) == 2
    assert sum("daily order budget" in line for line in r.log) == 2
    # next cycle: the budget is spent, which is routine, not a stop
    r2 = run(tr, NOW + 4 * H)
    assert r2.status == "ok" and len(ledger.q("SELECT * FROM orders WHERE status='resting'")) == 2


def test_resting_orders_count_against_the_caps(ledger, tmp_path):
    ex = FakeExchange(NOW)
    for i in range(4):
        ex.add(f"m{i}", event="one-event" if i < 2 else f"e{i}")
    ex, fc, tr = setup(ledger, tmp_path, {f"m{i}": 0.75 for i in range(4)}, ex=ex,
                       sizing={"max_event_pct": 0.03})
    run(tr)
    by = {o["market_id"]: o["usd"] for o in ledger.q("SELECT * FROM orders")}
    assert by["m0"] + by["m1"] <= 30.0 + 1e-6           # the event cap covers both resting orders
    assert by["m0"] > by["m1"]


def test_unsettled_closed_market_waits(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.75}, execution={"style": "taker"})
    run(tr)
    ex.close("cpi-above-3")                             # closed, no settlement published yet
    r = run(tr, NOW + 30 * 24 * H)
    assert len(ledger.positions()) == 1
    assert any("waiting for settlement" in line for line in r.log)


def test_odd_settlement_value_is_left_for_a_person(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.75}, execution={"style": "taker"})
    run(tr)
    ex.close("cpi-above-3", settlement=0.37)
    r = run(tr, NOW + 30 * 24 * H)
    assert len(ledger.positions()) == 1
    assert any("NOT settled" in line for line in r.log)


def test_live_mode_refuses(ledger, tmp_path, monkeypatch):
    from src import safety
    monkeypatch.delenv(safety.LIVE_CONFIRM_ENV, raising=False)
    with pytest.raises(safety.SafetyStop):
        Trader(cfg(account={"mode": "live"}), ledger, PolymarketUS(FakeExchange(NOW), min_interval=0), TableForecaster({}))
    monkeypatch.setenv(safety.LIVE_CONFIRM_ENV, safety.LIVE_CONFIRM_VALUE)
    with pytest.raises(NotImplementedError):
        Trader(cfg(account={"mode": "live"}), ledger, PolymarketUS(FakeExchange(NOW), min_interval=0), TableForecaster({}))


def test_market_closing_against_a_resting_order_counts_as_a_fill(ledger, tmp_path):
    """Between two cycles the event happens the wrong way and the market closes. A real resting bid would have
    been hit on the way down, so the paper account takes that loss too."""
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.70})
    run(tr)                                            # resting buy YES at 0.49
    ex.close("cpi-above-3")                            # closed, settlement not published yet
    r = run(tr, NOW + 30 * H)                          # past the order's 24 h life: it must NOT quietly expire
    assert ledger.q("SELECT status FROM orders")[0]["status"] == "resting"
    assert fc.asked == ["cpi-above-3"]                 # a closed market is not forecast again
    ex.close("cpi-above-3", settlement=0.0)            # YES lost
    r = run(tr, NOW + 40 * H)
    o = ledger.q("SELECT * FROM orders")[0]
    assert o["status"] == "filled" and any("assumed filled" in line for line in r.log)
    assert ledger.cash() == pytest.approx(1000.0 - o["shares"] * 0.49)
    assert ledger.positions() == []


def test_market_closing_in_favour_of_a_resting_order_counts_as_no_fill(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.70})
    run(tr)
    ex.close("cpi-above-3", settlement=1.0)            # YES won: nobody sold us the winner at 0.49
    run(tr, NOW + 4 * H)
    assert ledger.q("SELECT status FROM orders")[0]["status"] == "cancelled"
    assert ledger.cash() == pytest.approx(1000.0)
    assert ledger.market("cpi-above-3")["payout_yes"] == 1.0


def test_held_market_with_a_one_sided_book_does_not_crash_the_cycle(ledger, tmp_path):
    ex = FakeExchange(NOW).add("cpi-above-3").add("gdp")
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.75, "gdp": 0.75}, ex=ex, execution={"style": "taker"})
    run(tr)
    assert len(ledger.positions()) == 2
    ex._books["cpi-above-3"]["marketData"]["offers"] = []          # the asks vanish
    r = run(tr, NOW + 49 * H)
    assert r.status == "ok" and any("no two-sided market" in line for line in r.log)
    assert fc.asked.count("gdp") == 2                               # the other market is still looked after


def test_every_forecast_market_gets_its_outcome_recorded_even_if_never_traded(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.52})     # forecast, no trade
    run(tr)
    ex.set_book("cpi-above-3", 0.91, 0.93)                          # price leaves the tradable band for good
    for day in (2, 5, 9, 12):
        run(tr, NOW + day * 24 * H)
    assert ledger.market("cpi-above-3")["payout_yes"] is None
    ex.close("cpi-above-3", settlement=1.0)
    run(tr, NOW + 21 * 24 * H)
    assert ledger.market("cpi-above-3")["payout_yes"] == 1.0
    from src import scoring
    assert scoring.brier_vs_market(ledger).n == 1


def test_kill_switch_created_during_the_forecast_blocks_the_order(ledger, tmp_path):
    (tmp_path / "data").mkdir()
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.70},
                       on_call=lambda m: (tmp_path / "data" / "STOP.txt").write_text("stop"))   # Notepad adds .txt
    r = run(tr)
    assert r.status == "stopped" and ledger.q("SELECT * FROM orders") == []
    assert "kill switch" in ledger.q("SELECT reason FROM decisions")[0]["reason"]


def test_kill_switch_stops_a_resting_order_from_filling(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.70})
    run(tr)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "STOP").write_text("stop")
    ex.set_book("cpi-above-3", 0.47, 0.49)                          # the price comes to the order
    run(tr, NOW + 4 * H)
    assert ledger.positions() == [] and ledger.q("SELECT status FROM orders")[0]["status"] == "cancelled"


def test_position_awaiting_settlement_keeps_its_last_price(ledger, tmp_path):
    ex, fc, tr = setup(ledger, tmp_path, {"cpi-above-3": 0.75}, execution={"style": "taker"})
    r1 = run(tr)
    ex.close("cpi-above-3")                                         # closed, no settlement yet, no book
    r2 = run(tr, NOW + 30 * 24 * H)
    assert r2.status == "ok"
    assert r2.stats["equity"] == pytest.approx(r1.stats["equity"], abs=0.01)   # not marked to zero


def test_full_exit_leaves_no_dust(ledger, tmp_path, market):
    from src.book import Book, simulate_sell, summarize, floor_cents
    assert floor_cents(20.06) == 20.06 and floor_cents(20.069) == 20.06
    book = Book.from_levels("t", bids=[(0.48, 1000)], asks=[(0.50, 1000)])
    for shares in (20.06, 38.18, 0.07, 123.45):
        sold, _, _ = summarize(simulate_sell(book, shares, 0.40, depth_haircut=0.5))
        assert sold == pytest.approx(shares)
    ledger.upsert_market(market)
    ledger.deposit(100.0)
    ledger.apply_fill(None, "m1", "m1-yes", "YES", "BUY", 0.5, 20.06)
    ledger.apply_fill(None, "m1", "m1-yes", "YES", "SELL", 0.5, 20.057)
    assert ledger.positions() == []                                 # a sliver under half a cent is not a position


def test_config_typos_are_errors_not_silent_defaults(ledger, tmp_path):
    for section, key in (("sizing", "max_postion_pct"), ("safety", "max_drawdwn"), ("universe", "min_liquidty")):
        with pytest.raises(ValueError, match=key):
            ex, fc, tr = setup(ledger, tmp_path, {}, **{section: {key: 1}})
            run(tr)


def test_market_tick_fee_and_minimum_size_come_from_the_exchange(ledger, tmp_path):
    ex = (FakeExchange(NOW)
          .add("fine-tick", bid=0.480, ask=0.486, tick=0.001)
          .add("big-min", min_qty=100))
    ex, fc, tr = setup(ledger, tmp_path, {"fine-tick": 0.70, "big-min": 0.70}, ex=ex)
    r = run(tr)
    o = ledger.q("SELECT * FROM orders")
    assert len(o) == 1 and o[0]["market_id"] == "fine-tick"
    assert o[0]["limit_price"] == pytest.approx(0.481)          # one 0.001 tick inside the bid, not a whole cent
    assert any("minimum of 100 contracts" in line for line in r.log)


def test_taker_fee_uses_the_market_coefficient(ledger, tmp_path):
    ex = FakeExchange(NOW).add("cheap-fee", fee=0.02)
    ex, fc, tr = setup(ledger, tmp_path, {"cheap-fee": 0.75}, ex=ex, execution={"style": "taker"})
    run(tr)
    pos = ledger.positions()[0]
    assert ledger.one("SELECT SUM(fee) AS f FROM fills")["f"] == pytest.approx(pos["shares"] * 0.02 * 0.25, rel=1e-3)


def test_thin_market_is_forecast_and_scored_but_never_traded(ledger, tmp_path):
    ex = FakeExchange(NOW).add("thin", volume=120).add("deep")
    ex, fc, tr = setup(ledger, tmp_path, {"thin": 0.70, "deep": 0.52}, ex=ex)
    r = run(tr)
    assert fc.asked == ["deep", "thin"]                # the tradable market gets the first forecast slot
    assert ledger.q("SELECT * FROM orders") == []
    reasons = {d["market_id"]: d["reason"] for d in ledger.q("SELECT * FROM decisions")}
    assert "forecast only" in reasons["thin"]
    assert len(ledger.q("SELECT * FROM forecasts")) == 2


def test_untradable_markets_can_be_left_unforecast(ledger, tmp_path):
    ex = FakeExchange(NOW).add("thin", volume=120).add("deep")
    ex, fc, tr = setup(ledger, tmp_path, {}, ex=ex, universe={"forecast_untradable": False})
    run(tr)
    assert fc.asked == ["deep"]


def test_order_is_capped_at_a_share_of_the_nearby_depth(ledger, tmp_path):
    ex = FakeExchange(NOW).add("m", size=40)            # about $57 resting near the price on the thinner side
    ex, fc, tr = setup(ledger, tmp_path, {"m": 0.70}, ex=ex)
    run(tr)
    o = ledger.q("SELECT * FROM orders")[0]
    assert o["usd"] <= 0.25 * (0.48 * 40 + 0.47 * 80) + 0.01 and o["usd"] < 20.0
