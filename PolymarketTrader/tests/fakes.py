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
    """client.events.list / retrieve_by_slug, client.markets.retrieve_by_slug / book / settlement."""

    def __init__(self, now: float):
        self.now = now
        self._events: dict[str, dict] = {}
        self._books: dict[str, dict] = {}
        self._settled: dict[str, float] = {}
        self.calls: list[str] = []
        self.events = self._Events(self)
        self.markets = self._Markets(self)

    def add(self, slug: str, title: str = None, event: str = None, category: str = "economics", days: float = 20,
            bid: float = 0.48, ask: float = 0.50, size: float = 500, liquidity: float = 20000, volume: float = 80000,
            rules: str = RULES):
        event = event or f"ev-{slug}"
        ev = self._events.setdefault(event, {"id": len(self._events) + 1, "slug": event, "title": f"Event {event}",
                                              "description": "", "endTime": iso(self.now + days * 86400), "active": True,
                                              "closed": False, "tags": [{"id": 1, "slug": category, "label": category}],
                                              "markets": []})
        ev["markets"].append({"id": len(ev["markets"]) + 1, "slug": slug, "title": title or f"Will {slug} happen?",
                              "outcome": "Yes", "active": True, "closed": False, "liquidity": liquidity, "volume": volume,
                              "description": rules, "eventSlug": event})
        self.set_book(slug, bid, ask, size)
        return self

    def set_book(self, slug: str, bid: float, ask: float, size: float = 500, state: str = "MARKET_STATE_OPEN"):
        def lv(p, q):
            return {"px": {"value": f"{p:.2f}", "currency": "USD"}, "qty": str(q)}
        self._books[slug] = {"marketData": {"marketSlug": slug, "state": state,
                                            "bids": [lv(bid, size), lv(bid - 0.01, size * 2)],
                                            "offers": [lv(ask, size), lv(ask + 0.01, size * 2)]}}

    def close(self, slug: str, settlement: float | None = None):
        for ev in self._events.values():
            for m in ev["markets"]:
                if m["slug"] == slug:
                    m["closed"], m["active"] = True, False
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
            evs = [e for e in self.ex._events.values()]
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
            return {"market": self.ex._market(slug)[0]}

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
