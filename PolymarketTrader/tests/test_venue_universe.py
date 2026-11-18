import pytest

from fakes import RULES, FakeExchange
from src import universe
from src.venue import PolymarketUS, book_from_json, market_from_json, parse_time

NOW = 1_800_000_000.0


def test_parse_time_accepts_iso_seconds_and_milliseconds():
    assert parse_time("2027-01-15T08:00:00Z") == pytest.approx(NOW)
    assert parse_time("2027-01-15T08:00:00+00:00") == pytest.approx(NOW)
    assert parse_time(NOW) == NOW
    assert parse_time(NOW * 1000) == NOW
    assert parse_time(None) is None and parse_time("soon") is None


def test_market_from_json_reads_event_fields_and_tolerates_missing_ones():
    ev = {"slug": "fed-jan", "title": "Fed decision in January", "endTime": "2027-01-15T08:00:00Z",
          "description": "Resolves on the FOMC statement.", "tags": [{"id": 1, "slug": "economics", "label": "Economics"}],
          "markets": [{}, {}]}
    m = market_from_json({"id": 7, "slug": "fed-cut-25", "title": "25 bps cut", "outcome": "Yes",
                          "description": "Yes if the target range is lowered by 25 bps.", "liquidity": "1234.5"}, ev)
    assert m.market_id == "fed-cut-25" and m.event_id == "fed-jan" and m.category == "economics"
    assert m.question == "Fed decision in January: 25 bps cut"
    assert "25 bps" in m.rules and "FOMC" in m.rules
    assert m.end_ts == pytest.approx(NOW) and m.liquidity == pytest.approx(1234.5) and m.n_event_markets == 2
    assert m.yes_token == "fed-cut-25:YES" and m.no_token == "fed-cut-25:NO"
    bare = market_from_json({"slug": "x"})
    assert bare.question == "x" and bare.end_ts is None and bare.category is None and bare.rules == ""


def test_no_book_is_the_yes_book_mirrored():
    data = {"marketData": {"state": "MARKET_STATE_OPEN",
                           "bids": [{"px": {"value": "0.48", "currency": "USD"}, "qty": "100"},
                                    {"px": {"value": "0.47", "currency": "USD"}, "qty": "300"}],
                           "offers": [{"px": {"value": "0.50", "currency": "USD"}, "qty": "40"},
                                      {"px": {"value": "bad"}, "qty": "1"}]}}
    yes, no, state = book_from_json("m", data, now=5.0)
    assert state == "MARKET_STATE_OPEN" and yes.ts == 5.0
    assert (yes.best_bid, yes.best_ask) == (0.48, 0.50)
    assert no.best_ask == pytest.approx(0.52) and no.asks[0][1] == 100        # buying NO hits the YES bid
    assert no.best_bid == pytest.approx(0.50) and no.bids[0][1] == 40
    assert yes.mid + no.mid == pytest.approx(1.0)
    empty_yes, empty_no, st = book_from_json("m", {})
    assert empty_yes.best_bid is None and empty_no.best_ask is None and st is None


def test_listing_pages_until_a_short_page_and_skips_closed_markets():
    ex = FakeExchange(NOW)
    for i in range(7):
        ex.add(f"m{i}")
    ex.close("m3")
    v = PolymarketUS(ex, min_interval=0)
    got = v.list_markets(max_events=100, page=3)
    assert [m.market_id for m in got] == ["m0", "m1", "m2", "m4", "m5", "m6"]
    assert ex.calls.count("events.list") == 3
    assert v.list_markets(max_events=3, page=3)[-1].market_id == "m2"          # the scan cap holds


def test_settlement_is_none_until_published():
    ex = FakeExchange(NOW).add("m")
    v = PolymarketUS(ex, min_interval=0)
    assert v.settlement("m") is None
    ex.close("m", settlement=1.0)
    assert v.settlement("m") == 1.0


def test_throttle_spaces_requests(monkeypatch):
    slept = []
    monkeypatch.setattr("src.venue.time.sleep", lambda s: slept.append(s))
    v = PolymarketUS(FakeExchange(NOW).add("m"), min_interval=5.0)
    v.books("m")
    v.books("m")
    assert len(slept) == 1 and 0 < slept[0] <= 5.0 and v.requests == 2


# ---- universe ----------------------------------------------------------------

def mk(**kw):
    base = {"slug": "m", "title": "Will the unemployment rate be above 4.5%?", "outcome": "Yes", "description": RULES,
            "liquidity": 20000, "volume": 80000, "active": True, "closed": False}
    ev = {"slug": "e", "title": "Jobs report", "endTime": NOW + 20 * 86400,
          "tags": [{"id": 1, "slug": kw.pop("category", "economics"), "label": "x"}]}
    ev["endTime"] = NOW + kw.pop("days", 20) * 86400
    return market_from_json({**base, **kw}, ev)


ST = universe.settings({})


@pytest.mark.parametrize("kw, word", [
    ({}, ""),
    ({"closed": True}, "closed"),
    ({"days": 1}, "days to resolution"),
    ({"days": 400}, "days to resolution"),
    ({"category": "sports"}, "excluded"),
    ({"category": "crypto"}, "excluded"),
    ({"title": "Bitcoin up or down in the next hour?"}, "pattern"),
    ({"title": "Will the chair say 'recession' at the press conference?"}, "pattern"),
    ({"title": "Who will win the Nobel Peace Prize?"}, "pattern"),
    ({"title": "Will X strike Y before March?"}, "pattern"),
    ({"title": "Will the minister resign by June?"}, "pattern"),
    ({"title": "Will Acme complete its acquisition of Widgets?"}, "pattern"),
    ({"title": "Will the Fed announce a rate cut in March?"}, ""),
    ({"liquidity": 50}, "liquidity"),
    ({"volume": 10}, "volume"),
    ({"description": "tbd"}, "rules"),
])
def test_prefilter(kw, word):
    why = universe.prefilter(mk(**kw), ST, NOW)
    assert (why == "") if not word else (word in why)


def test_market_without_any_category_is_not_traded():
    m = mk()
    m.category, m.tags = None, []
    assert "no category" in universe.prefilter(m, ST, NOW)


def test_prefilter_needs_an_end_date_and_respects_the_allow_list():
    m = mk()
    m.end_ts = None
    assert "end date" in universe.prefilter(m, ST, NOW)
    only_politics = universe.settings({"universe": {"categories_allow": ["politics"]}})
    assert "allow list" in universe.prefilter(mk(), only_politics, NOW)
    assert universe.prefilter(mk(category="politics"), only_politics, NOW) == ""


@pytest.mark.parametrize("bid, ask, size, state, word", [
    (0.48, 0.50, 500, "MARKET_STATE_OPEN", ""),
    (0.48, 0.50, 500, "MARKET_STATE_SUSPENDED", "state"),
    (0.40, 0.50, 500, "MARKET_STATE_OPEN", "spread"),
    (0.05, 0.06, 5000, "MARKET_STATE_OPEN", "outside"),
    (0.93, 0.94, 5000, "MARKET_STATE_OPEN", "outside"),
    (0.48, 0.50, 10, "MARKET_STATE_OPEN", "at the touch"),
])
def test_book_check(bid, ask, size, state, word):
    ex = FakeExchange(NOW).add("m", bid=bid, ask=ask, size=size)
    yes, _, _ = PolymarketUS(ex, min_interval=0).books("m")
    why = universe.book_check(yes, state, ST)
    assert (why == "") if not word else (word in why)


def test_book_check_rejects_a_one_sided_book():
    yes, _, _ = book_from_json("m", {"marketData": {"bids": [{"px": {"value": "0.4"}, "qty": "10"}], "offers": []}})
    assert "one-sided" in universe.book_check(yes, None, ST)


def test_choose_puts_held_markets_first_and_skips_fresh_forecasts():
    ms = [mk(slug="a", liquidity=30000), mk(slug="b", liquidity=90000), mk(slug="c", liquidity=60000),
          mk(slug="held", category="sports")]
    for m in ms:
        m.event_id = m.market_id
    keep, dropped = universe.choose(ms, {}, {"c": NOW - 3600}, held={"held"}, now=NOW)
    assert [m.market_id for m in keep] == ["held", "b", "a"]        # a held market is re-forecast even if now filtered
    assert dropped["c"] == "forecast still fresh"
    keep, _ = universe.choose(ms, {}, {"c": NOW - 72 * 3600, "held": NOW - 3600}, held={"held"}, now=NOW)
    assert [m.market_id for m in keep] == ["b", "a", "c"]           # never-forecast markets before re-forecasts
