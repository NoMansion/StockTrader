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
    row = db.execute("SELECT ticker, yes_bid, no_ask, ask_contracts, fill_px, fill_shares, fee FROM obs").fetchone()
    assert row[0] == "LONG" and row[1:3] == pytest.approx((0.02, 0.98))
    assert row[3] == pytest.approx(400)                                 # the YES bids at 2c are the NO offers at 98c
    assert row[4] == pytest.approx(0.98) and row[5] * 0.98 + row[6] <= 20.0 and row[6] == pytest.approx(0.03)
    why = dict(db.execute("SELECT ticker, why FROM checked"))
    assert "FAR" not in why and "mid" in why["DRIFT"]
    # a second run the same day asks for nothing again
    before = http.requests
    assert sl.observe(venue, db, listing, {"economics"}, NOW + 3600, per_event=10)["looked"] == 0 and http.requests == before


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
