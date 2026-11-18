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
    ev = {"slug": "fed-jan", "title": "Fed decision in January", "endDate": "2020-01-01T00:00:00Z",
          "description": "Resolves on the FOMC statement.", "tags": [{"id": 1, "slug": "macro", "label": "Macro"}],
          "insiderTradingRules": "Fed staff may not trade.", "markets": [{}, {}]}
    m = market_from_json({"id": 7, "slug": "fed-cut-25", "title": "25 bps cut", "category": "macro",
                          "endDate": "2027-01-15T08:00:00Z", "status": "MARKET_STATUS_OPEN",
                          "orderPriceMinTickSize": 0.001, "minimumTradeQty": 0.01, "feeCoefficient": 0.095,
                          "bestBidQuote": {"value": "0.2200", "currency": "USD"}, "bestAskQuote": {"value": "0.2210"},
                          "marketSides": [{"description": "Yes", "long": True}, {"description": "No", "long": False}],
                          "description": "Yes if the target range is lowered by 25 bps."}, ev)
    assert m.market_id == "fed-cut-25" and m.event_id == "fed-jan" and m.category == "macro"
    assert m.question == "Fed decision in January: 25 bps cut" and m.outcome == "Yes"
    assert "25 bps" in m.rules and "FOMC" in m.rules and "Fed staff" in m.rules
    assert m.end_ts == pytest.approx(NOW)                       # the market's own end date, not the event's
    assert (m.tick, m.min_qty, m.fee_rate, m.best_bid, m.best_ask) == (0.001, 0.01, 0.095, 0.22, 0.221)
    assert m.n_event_markets == 2 and not m.closed
    assert market_from_json({"slug": "x", "status": "MARKET_STATUS_RESOLVED", "closed": False}).closed
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
    ex.add("game", category="sports")
    assert "game" in [m.market_id for m in v.list_markets()]
    assert "game" not in [m.market_id for m in v.list_markets(categories=["macro"])]   # filtered by the exchange


def test_real_payloads_parse():
    """Payloads captured from the live public API on 2026-11-18."""
    import json
    from pathlib import Path
    fx = json.loads((Path(__file__).parent / "fixtures" / "polymarket_us_cpi_yoy.json").read_text())
    ev = fx["event"]
    listed = [market_from_json(m, ev) for m in ev["markets"]]
    m = listed[1]
    assert m.category == "macro" and "economics" in m.tags and m.outcome == "Yes"
    assert m.event_id == ev["slug"] and "CPI YoY" in m.question and m.end_ts > 1_790_000_000
    assert m.fee_rate == 0.095 and m.tick in (0.01, 0.005, 0.0025, 0.001) and m.min_qty > 0
    assert "BLS" in m.rules and m.status == "MARKET_STATUS_OPEN" and not m.closed
    detail = market_from_json(fx["market_detail"]["market"])
    assert detail.market_id == m.market_id and detail.event_id is None      # the detail endpoint names no event
    yes, no, state = book_from_json(m.market_id, fx["book"])
    assert state == "MARKET_STATE_OPEN" and yes.best_bid < yes.best_ask
    assert yes.volume_usd > 0 and yes.open_interest > 0
    assert no.best_ask == pytest.approx(1 - yes.best_bid)
    assert fx["settlement_open_market"]["status_code"] == 404 and fx["settlement_settled_market"]["settlement"] in (0, 1)


def test_enrich_keeps_the_event_the_detail_endpoint_does_not_name():
    ex = FakeExchange(NOW).add("m", event="jobs-report")
    v = PolymarketUS(ex, min_interval=0)
    listed = v.list_markets()[0]
    assert v.market("m").event_id is None
    full = v.enrich(listed)
    assert full.event_id == "jobs-report" and full.question == listed.question and "macro" in full.tags
    assert full.question.count("Event jobs-report") == 1


def test_settlement_is_none_until_published():
    ex = FakeExchange(NOW).add("m")
    v = PolymarketUS(ex, min_interval=0)
    assert v.settlement("m") is None
    ex.close("m", settlement=1.0)
    assert v.settlement("m") == 1.0


def test_rate_limit_is_waited_out_once_then_reported(monkeypatch):
    slept = []
    monkeypatch.setattr("src.venue.time.sleep", lambda s: slept.append(s))

    class RateLimitError(Exception):
        status_code = 429

    ex = FakeExchange(NOW).add("m")
    real_book, state = ex.markets.book, {"fail": 1}

    def flaky(slug):
        if state["fail"] > 0:
            state["fail"] -= 1
            raise RateLimitError("<!doctype html><html>" + "x" * 5000)
        return real_book(slug)
    ex.markets.book = flaky
    v = PolymarketUS(ex, min_interval=0.5, rate_limit_pause=30)
    yes, _, _ = v.books("m")
    assert yes.best_bid == 0.48 and v.rate_limited == 1 and 30 in slept and v.min_interval == 1.0
    state["fail"] = 2
    with pytest.raises(RateLimitError) as err:
        v.books("m")
    from src.venue import brief
    assert brief(err.value) == "RateLimitError: HTML error page"


def test_throttle_spaces_requests(monkeypatch):
    slept = []
    monkeypatch.setattr("src.venue.time.sleep", lambda s: slept.append(s))
    v = PolymarketUS(FakeExchange(NOW).add("m"), min_interval=5.0)
    v.books("m")
    v.books("m")
    assert len(slept) == 1 and 0 < slept[0] <= 5.0 and v.requests == 2


# ---- universe ----------------------------------------------------------------

def mk(lite=True, **kw):
    """A market as it comes from the listing (lite) or from the detail endpoint."""
    days = kw.pop("days", 20)
    category = kw.pop("category", "macro")
    bid, ask = kw.pop("bid", 0.48), kw.pop("ask", 0.50)
    base = {"slug": "m", "title": "Will the unemployment rate be above 4.5%?", "description": RULES, "category": category,
            "endDate": NOW + days * 86400, "active": True, "closed": False, "status": "MARKET_STATUS_OPEN",
            "bestBidQuote": {"value": str(bid)} if bid is not None else None,
            "bestAskQuote": {"value": str(ask)} if ask is not None else None}
    ev = {"slug": "e", "title": "Jobs report", "tags": [{"id": 1, "slug": category, "label": "x"}]}
    m = market_from_json({**base, **kw}, ev)
    if lite:
        m.raw["lite"] = True
    return m


PM = {"universe": {"categories_allow": ["macro", "finance", "technology", "politics", "geopolitics", "science"],
                   "categories_deny": ["sports", "esports", "crypto", "culture", "climate", "weather", "mentions"]}}
ST = universe.settings(PM)                       # these tests use Polymarket's category names


@pytest.mark.parametrize("kw, word", [
    ({}, ""),
    ({"closed": True}, "closed"),
    ({"status": "MARKET_STATUS_SUSPENDED"}, "status"),
    ({"days": 1}, "days to resolution"),
    ({"days": 400}, "days to resolution"),
    ({"category": "sports"}, "excluded"),
    ({"category": "crypto"}, "excluded"),
    ({"category": "culture"}, "excluded"),
    ({"category": "pets"}, "allow list"),
    ({"title": "Bitcoin up or down in the next hour?"}, "pattern"),
    ({"title": "Will the chair say 'recession' at the press conference?"}, "pattern"),
    ({"title": "Who will win the Nobel Peace Prize?"}, "pattern"),
    ({"title": "Will X strike Y before March?"}, "pattern"),
    ({"title": "Will the minister resign by June?"}, "pattern"),
    ({"title": "Which World Leaders Will Leave Office in 2026?: Somebody"}, "pattern"),
    ({"title": "Who Will Be Announced Out of Their Admin Role in 2026?"}, "pattern"),
    ({"title": "Claude Opus 9 Released? By November 30"}, "pattern"),
    ({"title": "Which Company Has #1 AI Model end of 2026?: Anthropic"}, "pattern"),
    ({"title": "Which Company Has #1 AI Model end of 2026?: Google"}, "pattern"),
    ({"title": "Best Chinese AI Company end of November?: Xiaomi"}, "pattern"),
    ({"title": "Will Acme complete its acquisition of Widgets?"}, "pattern"),
    ({"title": "Will the Fed announce a rate cut in March?"}, ""),
    ({"bid": None}, "two-sided"),
    ({"bid": 0.40, "ask": 0.50}, "spread"),
    ({"bid": 0.03, "ask": 0.05}, "outside"),
    ({"bid": 0.93, "ask": 0.94}, "outside"),
])
def test_prefilter(kw, word):
    why = universe.prefilter(mk(**kw), ST, NOW)
    assert (why == "") if not word else (word in why), why


def test_full_detail_needs_rules_text_but_a_listing_row_does_not():
    assert "rules" in universe.prefilter(mk(lite=False, description="tbd"), ST, NOW)
    assert universe.prefilter(mk(lite=True, description="tbd"), ST, NOW) == ""
    assert universe.prefilter(mk(lite=False, bid=None), ST, NOW) == ""       # quotes are checked on the book instead


def test_market_without_any_category_is_not_traded():
    m = mk()
    m.category, m.tags = None, []
    assert "no category" in universe.prefilter(m, ST, NOW)


def test_prefilter_needs_an_end_date_and_respects_the_allow_list():
    m = mk()
    m.end_ts = None
    assert "end date" in universe.prefilter(m, ST, NOW)
    only_politics = universe.settings({"universe": {**PM["universe"], "categories_allow": ["politics"]}})
    assert "allow list" in universe.prefilter(mk(), only_politics, NOW)
    assert universe.prefilter(mk(category="politics"), only_politics, NOW) == ""
    anything = universe.settings({"universe": {**PM["universe"], "categories_allow": []}})
    assert universe.prefilter(mk(category="pets"), anything, NOW) == ""


@pytest.mark.parametrize("kw, state, word", [
    ({}, "MARKET_STATE_OPEN", ""),
    ({}, "MARKET_STATE_SUSPENDED", "state"),
    ({"bid": 0.40, "ask": 0.50}, "MARKET_STATE_OPEN", "spread"),
    ({"bid": 0.05, "ask": 0.06}, "MARKET_STATE_OPEN", "outside"),
    ({"bid": 0.93, "ask": 0.94}, "MARKET_STATE_OPEN", "outside"),
    ({"size": 2}, "MARKET_STATE_OPEN", "resting near"),
])
def test_book_check(kw, state, word):
    ex = FakeExchange(NOW).add("m", **kw)
    yes, _, _ = PolymarketUS(ex, min_interval=0).books("m")
    why = universe.book_check(yes, state, ST)
    assert (why == "") if not word else (word in why), why


def test_trade_tier_is_stricter_than_the_forecast_tier():
    v = PolymarketUS(FakeExchange(NOW).add("thin", volume=300).add("shallow", size=30).add("fine"), min_interval=0)
    for slug, word in (("thin", "traded so far"), ("shallow", "resting near"), ("fine", "")):
        yes, _, state = v.books(slug)
        assert universe.book_check(yes, state, ST) == ""              # all three are worth a forecast
        why = universe.trade_check(yes, ST)
        assert (why == "") if not word else (word in why), why


def test_depth_counts_what_sits_just_behind_the_best_price():
    """Seen live: 1 contract at the best ask, thousands one tick behind. That is a liquid market."""
    yes, _, _ = book_from_json("m", {"marketData": {
        "bids": [{"px": {"value": "0.48"}, "qty": "2"}, {"px": {"value": "0.47"}, "qty": "900"}],
        "offers": [{"px": {"value": "0.50"}, "qty": "1"}, {"px": {"value": "0.51"}, "qty": "800"}]}})
    assert yes.near_touch_usd(0.02) == pytest.approx(min(0.48 * 2 + 0.47 * 900, 0.50 + 0.51 * 800))
    assert universe.book_check(yes, "MARKET_STATE_OPEN", ST) == ""


def test_book_check_rejects_a_one_sided_book():
    yes, _, _ = book_from_json("m", {"marketData": {"bids": [{"px": {"value": "0.4"}, "qty": "10"}], "offers": []}})
    assert "one-sided" in universe.book_check(yes, None, ST)


def test_choose_puts_held_markets_first_and_skips_fresh_forecasts():
    ms = [mk(slug="a", bid=0.47, ask=0.50), mk(slug="b", bid=0.495, ask=0.50), mk(slug="c", bid=0.48, ask=0.50),
          mk(slug="held", category="sports")]
    for m in ms:
        m.event_id = m.market_id
    keep, dropped = universe.choose(ms, PM, {"c": NOW - 3600}, held={"held"}, now=NOW)
    assert [m.market_id for m in keep] == ["held", "b", "a"]        # a held market is re-forecast even if now filtered
    assert dropped["c"] == "forecast still fresh"
    keep, _ = universe.choose(ms, PM, {"c": NOW - 72 * 3600, "held": NOW - 3600}, held={"held"}, now=NOW)
    assert [m.market_id for m in keep] == ["b", "a", "c"]           # never-forecast markets before re-forecasts
