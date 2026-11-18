import pytest

from src.book import Book, simulate_buy, simulate_sell, summarize
from src.fees import FeeModel


def book():
    return Book.from_levels("t", bids=[{"price": "0.48", "size": "100"}, (0.47, 300)],
                            asks=[(0.52, 50), {"price": "0.50", "size": "40"}, (0.55, 1000)], ts=1.0)


def test_book_sorts_and_reports_the_touch():
    b = book()
    assert b.best_bid == 0.48 and b.best_ask == 0.50
    assert b.mid == pytest.approx(0.49) and b.spread == pytest.approx(0.02)
    assert b.depth_usd("buy", 0.52) == pytest.approx(0.50 * 40 + 0.52 * 50)
    assert b.depth_usd("sell", 0.48) == pytest.approx(48.0)


def test_buy_walks_the_asks_and_stops_at_the_limit():
    fills = simulate_buy(book(), usd=100.0, limit=0.52, depth_haircut=1.0)
    assert [(f.price, f.shares) for f in fills] == [(0.50, 40.0), (0.52, 50.0)]
    shares, avg, fee = summarize(fills)
    assert shares == 90 and avg == pytest.approx((20 + 26) / 90) and fee == 0


def test_buy_respects_the_budget_and_the_haircut():
    fills = simulate_buy(book(), usd=15.0, limit=0.55, depth_haircut=0.5)
    # half of the 40 shares at 0.50 = 20 shares = $10; then $5 at 0.52 = 9.61 shares
    assert fills[0].shares == 20.0 and fills[1].price == 0.52
    assert sum(f.price * f.shares for f in fills) <= 15.0 + 1e-9


def test_buy_includes_fees_in_the_budget():
    fee = FeeModel(taker_rate=0.10).fn()
    fills = simulate_buy(book(), usd=10.0, limit=0.50, fee_per_share=fee, depth_haircut=1.0)
    shares, avg, total_fee = summarize(fills)
    assert total_fee == pytest.approx(shares * 0.10 * 0.25, abs=1e-4)
    assert shares * avg + total_fee <= 10.0 + 1e-9


def test_nothing_fills_above_the_limit():
    assert simulate_buy(book(), usd=100.0, limit=0.49) == []
    assert simulate_sell(book(), shares=50, limit=0.49) == []


def test_sell_walks_the_bids():
    fills = simulate_sell(book(), shares=150, limit=0.47, depth_haircut=1.0)
    assert [(f.price, f.shares) for f in fills] == [(0.48, 100.0), (0.47, 50.0)]


def test_fee_shape():
    f = FeeModel(taker_rate=0.095, by_category={"geopolitics": 0.0})
    assert f.per_share(0.5) == pytest.approx(0.02375)
    assert f.per_share(0.9) == pytest.approx(0.095 * 0.09)
    assert f.per_share(0.5, maker=True) == 0.0
    assert f.per_share(0.5, category="Geopolitics") == 0.0
    assert f.per_share(0.5, market_rate=0.04) == pytest.approx(0.01)
    assert f.per_share(1.0) == 0.0


# ---- ledger ---------------------------------------------------------------

def test_buy_sell_settle_keep_cash_and_positions_consistent(ledger, market):
    ledger.upsert_market(market)
    ledger.deposit(1000.0)
    ledger.apply_fill(None, "m1", "m1-yes", "YES", "BUY", price=0.50, shares=40, fee=0.4)
    assert ledger.cash() == pytest.approx(1000 - 20.4)
    pos = ledger.position("m1-yes")
    assert pos["shares"] == 40 and pos["cost"] == pytest.approx(20.4)

    ledger.apply_fill(None, "m1", "m1-yes", "YES", "SELL", price=0.60, shares=10, fee=0.0)
    pos = ledger.position("m1-yes")
    assert pos["shares"] == 30 and pos["cost"] == pytest.approx(20.4 * 0.75)
    assert ledger.cash() == pytest.approx(1000 - 20.4 + 6.0)

    credited = ledger.settle("m1", payout_yes=1.0)
    assert credited == pytest.approx(30.0)
    assert ledger.positions() == []
    assert ledger.cash() == pytest.approx(1000 - 20.4 + 6.0 + 30.0)
    assert ledger.market("m1")["payout_yes"] == 1.0


def test_no_side_settles_at_one_minus_payout(ledger, market):
    ledger.upsert_market(market)
    ledger.deposit(100.0)
    ledger.apply_fill(None, "m1", "m1-no", "NO", "BUY", price=0.40, shares=50)
    assert ledger.settle("m1", payout_yes=1.0) == 0.0
    assert ledger.cash() == pytest.approx(80.0)


def test_fifty_fifty_resolution(ledger, market):
    ledger.upsert_market(market)
    ledger.deposit(100.0)
    ledger.apply_fill(None, "m1", "m1-yes", "YES", "BUY", price=0.40, shares=50)
    assert ledger.settle("m1", payout_yes=0.5) == pytest.approx(25.0)


def test_cannot_overspend_or_oversell(ledger, market):
    ledger.upsert_market(market)
    ledger.deposit(10.0)
    with pytest.raises(ValueError):
        ledger.apply_fill(None, "m1", "m1-yes", "YES", "BUY", price=0.50, shares=40)
    assert ledger.cash() == pytest.approx(10.0) and ledger.positions() == []     # rolled back
    ledger.apply_fill(None, "m1", "m1-yes", "YES", "BUY", price=0.50, shares=10)
    with pytest.raises(ValueError):
        ledger.apply_fill(None, "m1", "m1-yes", "YES", "SELL", price=0.50, shares=11)
    assert ledger.position("m1-yes")["shares"] == 10


def test_exposure_by_market_event_category(ledger, market):
    ledger.upsert_market(market)
    ledger.upsert_market({**market, "market_id": "m2", "yes_token": "m2-yes", "no_token": "m2-no"})
    ledger.upsert_market({**market, "market_id": "m3", "event_id": "e9", "category": "economics",
                          "yes_token": "m3-yes", "no_token": "m3-no"})
    ledger.deposit(1000.0)
    ledger.apply_fill(None, "m1", "m1-yes", "YES", "BUY", 0.5, 20)
    ledger.apply_fill(None, "m2", "m2-no", "NO", "BUY", 0.25, 40)
    ledger.apply_fill(None, "m3", "m3-yes", "YES", "BUY", 0.5, 10)
    e = ledger.exposure(market_id="m1", event_id="e1", category="politics")
    assert e == {"total": pytest.approx(25.0), "market": pytest.approx(10.0), "event": pytest.approx(20.0),
                 "category": pytest.approx(20.0)}


def test_equity_marks_at_the_bid(ledger, market):
    ledger.upsert_market(market)
    ledger.deposit(100.0)
    ledger.apply_fill(None, "m1", "m1-yes", "YES", "BUY", 0.50, 40)
    row = ledger.record_equity({"m1-yes": (0.48, 0.49)}, ts=10.0)
    assert row["equity"] == pytest.approx(80 + 40 * 0.48)
    assert row["positions_mid"] == pytest.approx(40 * 0.49)
    assert ledger.high_water() == pytest.approx(99.2)
    assert ledger.deposits() == pytest.approx(100.0)
    # a position with no bid is worth nothing on the bid basis
    assert ledger.record_equity({}, ts=11.0)["equity"] == pytest.approx(80.0)
