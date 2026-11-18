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
