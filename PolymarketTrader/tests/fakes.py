"""An offline stand-in for the polymarket-us SDK client, returning JSON shaped like the SDK's types, and a
forecaster that answers from a table."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from src.forecast import Forecast


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class NotFoundError(Exception):
    status_code = 404


RULES = ("This market resolves to Yes if the Bureau of Labor Statistics reports the figure described in the title "
         "in its scheduled release, according to bls.gov. Otherwise it resolves to No.")


class FakeExchange:
    """client.events.list / retrieve_by_slug, client.markets.retrieve_by_slug / book / settlement, answering in
    the shape the live API used on 2026-11-18 (see tests/fixtures): no liquidity figure in listings, quotes and
    tick size on the market, traded dollars in the book's statistics, no event slug on the market detail."""

    def __init__(self, now: float):
        self.now = now
        self._events: dict[str, dict] = {}
        self._books: dict[str, dict] = {}
        self._settled: dict[str, float] = {}
        self.calls: list[str] = []
        self.events = self._Events(self)
        self.markets = self._Markets(self)

    def add(self, slug: str, title: str = None, event: str = None, category: str = "macro", days: float = 20,
            bid: float = 0.48, ask: float = 0.50, size: float = 500, volume: float = 80000, rules: str = RULES,
            tick: float = 0.01, fee: float = 0.095, min_qty: float = 0.01):
        event = event or f"ev-{slug}"
        ev = self._events.setdefault(event, {"id": str(len(self._events) + 1), "slug": event, "title": f"Event {event}",
                                              "description": "", "category": category,
                                              "endDate": iso(self.now + days * 86400), "active": True, "closed": False,
                                              "insiderTradingRules": None,
                                              "tags": [{"id": "1", "slug": category, "label": category.title()}],
                                              "markets": []})
        ev["markets"].append({"id": str(len(ev["markets"]) + 1), "slug": slug, "title": title or f"Will {slug} happen?",
                              "question": ev["title"], "description": rules, "category": category,
                              "endDate": iso(self.now + days * 86400), "active": True, "closed": False,
                              "status": "MARKET_STATUS_OPEN", "orderPriceMinTickSize": tick, "minimumTradeQty": min_qty,
                              "feeCoefficient": fee, "tags": [],
                              "marketSides": [{"description": "Yes", "long": True}, {"description": "No", "long": False}]})
        self._volume = getattr(self, "_volume", {})
        self._volume[slug] = volume
        self.set_book(slug, bid, ask, size)
        return self

    def set_book(self, slug: str, bid: float, ask: float, size: float = 500, state: str = "MARKET_STATE_OPEN"):
        def lv(p, q):
            return {"px": {"value": f"{p:.4f}", "currency": "USD"}, "qty": f"{q:.4f}"}
        m, _ = self._market(slug)
        tick = m["orderPriceMinTickSize"]
        m["bestBidQuote"] = {"value": f"{bid:.4f}", "currency": "USD"}
        m["bestAskQuote"] = {"value": f"{ask:.4f}", "currency": "USD"}
        self._books[slug] = {"marketData": {"marketSlug": slug, "state": state,
                                            "bids": [lv(bid, size), lv(bid - tick, size * 2)],
                                            "offers": [lv(ask, size), lv(ask + tick, size * 2)],
                                            "stats": {"notionalTraded": {"value": str(self._volume[slug]), "currency": "USD"},
                                                      "openInterest": "5000.0000"}}}

    def close(self, slug: str, settlement: float | None = None):
        m, _ = self._market(slug)
        m["closed"], m["active"], m["status"] = True, False, "MARKET_STATUS_RESOLVED"
        if settlement is not None:
            self._settled[slug] = settlement

    def _market(self, slug):
        for ev in self._events.values():
            for m in ev["markets"]:
                if m["slug"] == slug:
                    return m, ev
        raise NotFoundError(slug)

    class _Events:
        def __init__(self, ex):
            self.ex = ex

        def list(self, params=None):
            self.ex.calls.append("events.list")
            p = params or {}
            evs = [e for e in self.ex._events.values()
                   if not p.get("categories") or e["category"] in p["categories"]]
            off, lim = int(p.get("offset", 0)), int(p.get("limit", 50))
            return {"events": evs[off:off + lim]}

        def retrieve_by_slug(self, slug):
            self.ex.calls.append(f"events.retrieve_by_slug:{slug}")
            return {"event": self.ex._events[slug]}

    class _Markets:
        def __init__(self, ex):
            self.ex = ex

        def retrieve_by_slug(self, slug):
            self.ex.calls.append(f"markets.retrieve_by_slug:{slug}")
            return {"market": dict(self.ex._market(slug)[0])}

        def book(self, slug):
            self.ex.calls.append(f"markets.book:{slug}")
            return self.ex._books[slug]

        def settlement(self, slug):
            self.ex.calls.append(f"markets.settlement:{slug}")
            if slug not in self.ex._settled:
                raise NotFoundError(slug)
            return {"slug": slug, "settlement": self.ex._settled[slug]}


class TableForecaster:
    """market_id -> probability (or a dict of Forecast fields). Markets not in the table get no forecast."""

    name = "table"

    def __init__(self, table: dict, on_call=None):
        self.table, self.on_call, self.asked = table, on_call, []

    def forecast(self, m, now=None):
        self.asked.append(m.market_id)
        if self.on_call:
            self.on_call(m)
        v = self.table.get(m.market_id)
        if v is None:
            return None
        kw = {"p_yes": v} if not isinstance(v, dict) else dict(v)
        base = {"market_id": m.market_id, "p_runs": [kw["p_yes"]] * 3, "confidence": "medium", "rules_clear": True,
                "flags": [], "rationale": "table", "backend": self.name, "model": "none", "ts": now or time.time()}
        return Forecast(**{**base, **kw})


class FakeKalshiHTTP:
    """Stands in for src.kalshi_http.KalshiHTTP: answers the public paths the adapter uses, in the live shapes
    (see tests/fixtures/kalshi_cpi_yoy.json)."""

    def __init__(self, now: float):
        self.now, self.requests, self.rate_limited = now, 0, 0
        self.series = {"KXCPIYOY": {"ticker": "KXCPIYOY", "category": "Economics", "fee_type": "quadratic_with_maker_fees",
                                    "fee_multiplier": 1, "tags": ["Inflation"]},
                       "KXNBA": {"ticker": "KXNBA", "category": "Sports", "fee_type": "quadratic", "fee_multiplier": 1, "tags": []}}
        self.markets: dict[str, dict] = {}
        self.books: dict[str, dict] = {}
        self.page_size = 0                          # 0 = everything on one page
        self.fail_markets = 0                       # how many /markets requests to refuse with a 429

    def add(self, ticker: str, series: str = "KXCPIYOY", days: float = 20, bid: float = 0.48, ask: float = 0.50,
            size: float = 500, volume: float = 50000, title: str = None):
        event = f"{series}-26NOV"
        self.markets[ticker] = {
            "ticker": ticker, "event_ticker": event, "status": "active", "result": "", "market_type": "binary",
            "title": title or f"Will {ticker} be above the threshold?", "yes_sub_title": "Above 3.6%",
            "rules_primary": "If the Consumer Price Index increases by more than 3.6% in the twelve months ending "
                             "November 2026, as reported by the Bureau of Labor Statistics, then the market resolves to Yes.",
            "rules_secondary": "", "close_time": iso(self.now + days * 86400), "volume_fp": f"{volume:.2f}",
            "open_interest_fp": "9000.00", "price_ranges": [{"start": "0.0000", "end": "1.0000", "step": "0.0100"}]}
        self.set_book(ticker, bid, ask, size)
        return self

    def set_book(self, ticker: str, bid: float, ask: float, size: float = 500):
        m = self.markets[ticker]
        m["yes_bid_dollars"], m["yes_ask_dollars"] = f"{bid:.4f}", f"{ask:.4f}"
        self.books[ticker] = {"orderbook_fp": {
            "yes_dollars": [[f"{bid - 0.01:.4f}", f"{size * 2:.2f}"], [f"{bid:.4f}", f"{size:.2f}"]],
            "no_dollars": [[f"{1 - ask - 0.01:.4f}", f"{size * 2:.2f}"], [f"{1 - ask:.4f}", f"{size:.2f}"]]}}

    def settle(self, ticker: str, result: str):
        self.markets[ticker].update(status="finalized", result=result,
                                    settlement_value_dollars="1.0000" if result == "yes" else "0.0000")

    def get(self, path: str, tries: int = 6, **params):
        from src.kalshi_http import KalshiError
        self.requests += 1
        if path == "/series":
            return {"series": [s for s in self.series.values() if s["category"] == params.get("category")]}
        if path.startswith("/series/"):
            return {"series": self.series[path.split("/")[2]]}
        if path == "/markets":
            lo, hi = params.get("min_close_ts", 0), params.get("max_close_ts", 9e18)
            from src.venue import parse_time
            if self.fail_markets:
                self.fail_markets -= 1
                raise KalshiError(429, path, "too many requests")
            live = [m for m in self.markets.values() if m["status"] == "active" and lo <= parse_time(m["close_time"]) <= hi]
            size = self.page_size or len(live) or 1
            start = int(params.get("cursor") or 0)
            nxt = start + size
            return {"markets": live[start:nxt], "cursor": str(nxt) if nxt < len(live) else ""}
        if path.startswith("/markets/") and path.endswith("/orderbook"):
            return self.books[path.split("/")[2]]
        if path.startswith("/markets/"):
            t = path.split("/")[2]
            if t not in self.markets:
                raise KalshiError(404, path, "not found")
            return {"market": dict(self.markets[t])}
        if path.startswith("/events/"):
            return {"event": {"event_ticker": path.split("/")[2], "title": "CPI YoY in November", "category": "Economics",
                              "settlement_sources": [{"name": "Bureau of Labor Statistics", "url": "https://www.bls.gov/cpi/"}]}}
        raise KalshiError(404, path, "not found")

    def pages(self, path: str, key: str, **params):
        params.pop("limit", None); params.pop("max_pages", None); params.pop("tries", None)
        yield from self.get(path, **params)[key]
