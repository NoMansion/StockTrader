"""The forward observation log for the longshot rule: it records what was on offer and never orders anything."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import shadow_longshot as sl  # noqa: E402
from fakes import FakeKalshiHTTP  # noqa: E402
from src.kalshi import Kalshi  # noqa: E402

NOW = 1_800_000_000.0


def setup(tmp_path):
    http = FakeKalshiHTTP(NOW)
    http.add("LONG", days=10, bid=0.02, ask=0.03, size=400, volume=90000)        # qualifies
    http.add("MID", days=10, bid=0.30, ask=0.32, volume=90000)                    # not a longshot
    http.add("FAR", days=200, bid=0.02, ask=0.03, volume=90000)                   # ends too far away
    http.add("THIN", days=10, bid=0.02, ask=0.03, volume=500)                     # has not traded enough
    http.add("DRIFT", days=10, bid=0.02, ask=0.03, volume=90000)                  # listed cheap, no longer cheap
    listing = {"markets": [dict(m) for m in http.markets.values()]}
    http.set_book("DRIFT", 0.20, 0.22)
    venue = Kalshi(http=http, clock=lambda: NOW)
    venue._load_series(["Economics"])
    return http, venue, listing, sqlite3.connect(str(tmp_path / "shadow.db"))


def test_only_markets_that_meet_the_rule_on_a_fresh_book_are_recorded(tmp_path):
    http, venue, listing, db = setup(tmp_path)
    res = sl.observe(venue, db, listing, {"economics"}, NOW, per_event=10)
    assert res["recorded"] == 1 and res["looked"] == 2                  # MID, THIN and FAR never cost a request
    assert db.execute("SELECT ev_markets FROM obs").fetchone()[0] == 5   # the event's size is noted (five markets here)
    row = db.execute("SELECT ticker, yes_bid, no_ask, ask_contracts, fill_px, fill_shares, fee FROM obs").fetchone()
    assert row[0] == "LONG" and row[1:3] == pytest.approx((0.02, 0.98))
    assert row[3] == pytest.approx(400)                                 # the YES bids at 2c are the NO offers at 98c
    assert row[4] == pytest.approx(0.98) and row[5] * 0.98 + row[6] <= 20.0 and row[6] == pytest.approx(0.03)
    why = dict(db.execute("SELECT ticker, why FROM checked"))
    assert "FAR" not in why and "mid" in why["DRIFT"]
    # a second run the same day looks at no market again; its one request reads the trades behind the resting bid
    before = http.requests
    assert sl.observe(venue, db, listing, {"economics"}, NOW + 3600, per_event=10)["looked"] == 0 and http.requests == before + 1


def test_settlement_is_recorded_and_reported(tmp_path):
    http, venue, listing, db = setup(tmp_path)
    sl.observe(venue, db, listing, {"economics"}, NOW, per_event=10)
    assert "none of them has settled" in sl.report(db)
    http.settle("LONG", "no")
    res = sl.observe(venue, db, listing, {"economics"}, NOW + 11 * 86400, per_event=10)
    assert res["settled"] == 1
    text = sl.report(db)
    assert "1 with a fill, 0 lost" in text and "+1." in text            # bought NO at 98c plus a 3c fee on $20: about +1.9%


def test_fee_is_rounded_up_to_the_cent():
    assert sl.order_fee(0.07, 0.98, 20.0) == pytest.approx(0.03)        # 0.07 x 20 x 0.98 x 0.02 = 2.7 cents
    assert sl.order_fee(0.07, 0.50, 100.0) == pytest.approx(1.75)


def test_a_resting_bid_fills_only_after_the_queue_ahead_or_on_a_trade_through(tmp_path):
    http, venue, listing, db = setup(tmp_path)
    sl.observe(venue, db, listing, {"economics"}, NOW, per_event=10)
    px, ahead = db.execute("SELECT rest_px, rest_ahead FROM obs WHERE ticker='LONG'").fetchone()
    assert px == pytest.approx(0.97) and ahead == pytest.approx(400)       # the NO bid at 97c is the YES ask at 3c
    # buyers of YES take 300 at the ask: not enough to reach an order behind 400
    http.trade("LONG", NOW + 3600, 0.03, 300)
    http.trade("LONG", NOW + 3700, 0.02, 5000, taker_side="no")            # sellers of YES do not touch NO bids
    assert sl.track_resting(venue, db, NOW + 2 * 3600) == 0
    assert db.execute("SELECT COALESCE(rest_done, 0) FROM obs").fetchone()[0] == 0
    # another 130: 430 traded at the price, past the 400 ahead plus our 20.6 contracts
    http.trade("LONG", NOW + 5 * 3600, 0.03, 130)
    assert sl.track_resting(venue, db, NOW + 6 * 3600) == 1
    assert db.execute("SELECT rest_filled, rest_fill_ts FROM obs").fetchone() == (1, NOW + 5 * 3600)
    assert "1 decided, 1 filled" in sl.report(db)


def test_a_resting_bid_nobody_reached_is_recorded_as_unfilled_after_three_days(tmp_path):
    http, venue, listing, db = setup(tmp_path)
    sl.observe(venue, db, listing, {"economics"}, NOW, per_event=10)
    http.trade("LONG", NOW + 3600, 0.03, 50)
    http.trade("LONG", NOW + 80 * 3600, 0.05, 900)                         # a trade through, but after the window
    assert sl.track_resting(venue, db, NOW + 24 * 3600) == 0               # window still open
    assert sl.track_resting(venue, db, NOW + 73 * 3600) == 1
    assert db.execute("SELECT rest_filled, rest_done FROM obs").fetchone() == (0, 1)
    assert sl.resting_fill([{"taker_side": "yes", "yes_price_dollars": "0.0400", "count_fp": "1", "created_time": "2026-01-01T00:00:00Z"}],
                           0.03, None) is not None                         # through the price: filled whatever the queue
