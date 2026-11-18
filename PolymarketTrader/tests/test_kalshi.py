import json
from pathlib import Path

import pytest

from fakes import FakeKalshiHTTP, TableForecaster
from src.kalshi import Kalshi, books_from_kalshi, market_from_kalshi, series_of
from src.kalshi_http import KalshiError, KalshiHTTP
from src.trader import Trader

NOW = 1_800_000_000.0
H = 3600.0
FX = json.loads((Path(__file__).parent / "fixtures" / "kalshi_cpi_yoy.json").read_text())


def test_real_market_parses():
    m = market_from_kalshi(FX["listing_market"], FX["series"]["series"], FX["event"])
    assert m.market_id == "KXCPIYOY-26NOV-T3.6" and m.event_id == "KXCPIYOY-26NOV" and series_of(m.event_id) == "KXCPIYOY"
    assert m.category == "economics" and m.outcome == "Above 3.6%" and m.status == "MARKET_STATUS_OPEN"
    assert "CPI inflation be above 3.6%" in m.question
    assert "Bureau of Labor Statistics" in m.rules and "bls.gov" in m.rules
    assert (m.best_bid, m.best_ask, m.tick) == (0.80, 0.81, 0.01)
    assert m.fee_rate == pytest.approx(0.07) and m.maker_fee_rate == pytest.approx(0.0175)    # this series charges makers
    assert m.volume == pytest.approx(141502.27 * 0.805) and m.open_interest == pytest.approx(79043.22)
    assert not m.closed and m.end_ts > 1_790_000_000
    plain = market_from_kalshi(FX["listing_market"], {"category": "Economics", "fee_type": "quadratic", "fee_multiplier": 1})
    assert plain.maker_fee_rate == 0.0


def test_real_order_book_yes_ask_is_the_no_bid_mirrored():
    yes, no = books_from_kalshi("T", FX["orderbook"], now=5.0)
    assert yes.best_bid == 0.80 and no.best_bid == 0.19
    assert yes.best_ask == pytest.approx(0.81) and no.best_ask == pytest.approx(0.20)
    assert yes.bids[0][1] == pytest.approx(15156.15) and yes.asks[0][1] == pytest.approx(17925.0)
    assert yes.ts == 5.0
    old_shape, _ = books_from_kalshi("T", {"orderbook": {"yes": [[80, 10]], "no": [[19, 5]]}})
    assert old_shape.best_bid == 0.80 and old_shape.best_ask == pytest.approx(0.81)
    empty, _ = books_from_kalshi("T", {})
    assert empty.best_bid is None


def test_settled_market_and_empty_quotes():
    settled = market_from_kalshi(FX["settled_markets"][0])
    assert settled.closed
    no_quote = market_from_kalshi({**FX["listing_market"], "yes_bid_dollars": "0.0000", "yes_ask_dollars": "1.0000"})
    assert no_quote.best_bid is None and no_quote.best_ask is None


def test_listing_keeps_only_allowed_categories_and_needs_an_allow_list():
    http = FakeKalshiHTTP(NOW).add("KXCPIYOY-26NOV-T3.6").add("KXNBA-GAME1", series="KXNBA").add("KXCPIYOY-FAR", days=300)
    v = Kalshi(http=http, clock=lambda: NOW)
    got = v.list_markets(categories=["economics"], min_days=3, max_days=75)
    assert [m.market_id for m in got] == ["KXCPIYOY-26NOV-T3.6"]
    assert got[0].category == "economics" and got[0].maker_fee_rate == pytest.approx(0.0175)
    with pytest.raises(ValueError):
        v.list_markets(categories=None)


def test_series_list_is_cached_on_disk(tmp_path):
    http = FakeKalshiHTTP(NOW).add("KXCPIYOY-26NOV-T3.6")
    Kalshi(http=http, clock=lambda: NOW, cache_dir=tmp_path).list_markets(categories=["Economics"])
    assert (tmp_path / "kalshi_series.json").exists()
    http2 = FakeKalshiHTTP(NOW).add("KXCPIYOY-26NOV-T3.6")
    http2.series = {}                                    # a second run needs no series request at all
    got = Kalshi(http=http2, clock=lambda: NOW, cache_dir=tmp_path).list_markets(categories=["Economics"])
    assert len(got) == 1


def test_settlement_and_closed():
    http = FakeKalshiHTTP(NOW).add("A")
    v = Kalshi(http=http, clock=lambda: NOW)
    assert v.settlement("A") is None and not v.is_closed("A")
    http.settle("A", "yes")
    assert v.settlement("A") == 1.0 and v.is_closed("A") and v.market("A").closed
    http.settle("A", "no")
    assert v.settlement("A") == 0.0
    assert v.market("MISSING") is None and v.settlement("MISSING") is None


def test_enrich_adds_the_settlement_sources():
    http = FakeKalshiHTTP(NOW).add("A")
    v = Kalshi(http=http, clock=lambda: NOW)
    listed = v.list_markets(categories=["economics"], min_days=3, max_days=75)[0]
    full = v.enrich(listed)
    assert "Bureau of Labor Statistics" in full.rules and full.event_title == "CPI YoY in November"


def cfg():
    return {"account": {"mode": "paper", "venue": "kalshi"},
            "universe": {"categories_allow": ["economics"], "categories_deny": ["sports"]},
            "forecaster": {}, "sizing": {"shrink_weight": 0.5, "max_disagreement": 0.3}, "execution": {"style": "passive"},
            "fees": {"taker_rate": 0.07, "round_up_cents": True}, "safety": {}}


def run(tr, http, now):
    tr._books.clear(); tr._markets.clear()
    tr.venue.clock = lambda: now
    http.now = now
    return tr.run(now=now)


def test_full_cycle_on_kalshi_with_maker_fee_rounded_up(ledger, tmp_path):
    http = FakeKalshiHTTP(NOW).add("KXCPIYOY-26NOV-T3.6")
    ledger.deposit(1000.0)
    fc = TableForecaster({"KXCPIYOY-26NOV-T3.6": 0.70})
    tr = Trader(cfg(), ledger, Kalshi(http=http, clock=lambda: NOW), fc, root=tmp_path)
    r = run(tr, http, NOW)
    o = ledger.q("SELECT * FROM orders")
    assert len(o) == 1 and o[0]["status"] == "resting" and o[0]["limit_price"] == pytest.approx(0.49), r.log
    assert ledger.market("KXCPIYOY-26NOV-T3.6")["maker_fee_rate"] == pytest.approx(0.0175)
    http.set_book("KXCPIYOY-26NOV-T3.6", 0.47, 0.49)                     # the ask comes down to the order
    run(tr, http, NOW + 4 * H)
    pos = ledger.positions()
    assert len(pos) == 1
    raw = 0.0175 * 0.49 * 0.51 * pos[0]["shares"]
    fee = ledger.one("SELECT SUM(fee) AS f FROM fills")["f"]
    assert fee >= raw and fee == pytest.approx(__import__("math").ceil(raw * 100 - 1e-9) / 100)   # up to the cent
    http.settle("KXCPIYOY-26NOV-T3.6", "yes")
    r3 = run(tr, http, NOW + 30 * 24 * H)
    assert ledger.positions() == [] and ledger.cash() > 1000.0
    assert any("settled" in line for line in r3.log)


def test_http_client_waits_out_a_rate_limit(monkeypatch):
    monkeypatch.setattr("src.kalshi_http.time.sleep", lambda s: None)

    class Resp:
        def __init__(self, code, body=None):
            self.status_code, self._body, self.headers, self.text = code, body or {}, {}, "too many requests"

        def json(self):
            return self._body

    class Client:
        def __init__(self, answers):
            self.answers, self.calls = list(answers), 0

        def get(self, url, params=None):
            self.calls += 1
            return self.answers.pop(0)

    c = Client([Resp(429), Resp(500), Resp(200, {"ok": 1})])
    k = KalshiHTTP(min_interval=0, client=c)
    assert k.get("/x", a=None, b=2) == {"ok": 1} and c.calls == 3 and k.rate_limited == 1 and k.min_interval > 0
    with pytest.raises(KalshiError) as e:
        KalshiHTTP(min_interval=0, client=Client([Resp(404)])).get("/x")
    assert e.value.status_code == 404
    with pytest.raises(KalshiError):
        KalshiHTTP(min_interval=0, client=Client([Resp(429), Resp(429)])).get("/x", tries=2)
    pager = KalshiHTTP(min_interval=0, client=Client([Resp(200, {"markets": [1, 2], "cursor": "c"}), Resp(200, {"markets": [3], "cursor": ""})]))
    assert list(pager.pages("/markets", "markets")) == [1, 2, 3]
