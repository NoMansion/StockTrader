"""Market data from Polymarket US, the CFTC-regulated venue open to US residents (gateway.polymarket.us).

Everything here is a public, read-only GET: no keys, no account. The official `polymarket-us` SDK is used when it
is installed; any object with the same `events` / `markets` methods works, which is how the tests run offline.

How the venue models a market (from the SDK's types, polymarket-us 2.4.1):
  - a market is identified by its `slug`; it belongs to an event (`eventSlug`)
  - there is ONE order book per market, quoted for the "long" side (YES). Buying NO is a "short" order
    (ORDER_INTENT_BUY_SHORT). The NO book is therefore the YES book mirrored: NO ask = 1 - YES bid.
  - prices are {"value": "0.55", "currency": "USD"}; quantities are strings of contracts

Field names beyond the SDK's typed ones are read defensively (several spellings, missing = None), because the
API returns more than the SDK declares and the SDK types are marked partial.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .book import Book

OPEN_STATES = {"MARKET_STATE_OPEN"}


@dataclass
class Market:
    market_id: str                      # the venue slug
    question: str
    rules: str = ""
    event_id: str | None = None
    event_title: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    end_ts: float | None = None
    active: bool = True
    closed: bool = False
    liquidity: float | None = None
    volume: float | None = None
    outcome: str | None = None          # what the long side stands for ("Yes", a team, a candidate)
    n_event_markets: int = 1
    raw: dict = field(default_factory=dict)

    @property
    def yes_token(self) -> str:
        return f"{self.market_id}:YES"

    @property
    def no_token(self) -> str:
        return f"{self.market_id}:NO"

    def days_to_end(self, now: float | None = None) -> float | None:
        if self.end_ts is None:
            return None
        return (self.end_ts - (now or time.time())) / 86400.0

    def ledger_row(self) -> dict:
        return {"market_id": self.market_id, "slug": self.market_id, "question": self.question, "rules": self.rules,
                "event_id": self.event_id, "event_title": self.event_title, "category": self.category,
                "end_ts": self.end_ts, "yes_token": self.yes_token, "no_token": self.no_token}


def parse_time(v) -> float | None:
    """ISO-8601 string, epoch seconds or epoch milliseconds -> epoch seconds."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v) / 1000.0 if v > 1e11 else float(v)
    try:
        s = str(v).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _first(d: dict, *keys, default=None):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return default


def _num(v) -> float | None:
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _labels(items) -> list[str]:
    out = []
    for t in items or []:
        if isinstance(t, dict):
            t = _first(t, "slug", "label", "name")
        if t:
            out.append(str(t).lower())
    return out


def market_from_json(m: dict, event: dict | None = None) -> Market:
    """One market (optionally with its parent event) -> Market."""
    event = event or {}
    tags = _labels(event.get("tags")) + _labels(m.get("tags"))
    cats = _labels(_first(event, "categories", default=[])) + _labels(_first(m, "categories", default=[]))
    cat = _first(m, "category", default=None) or _first(event, "category", default=None)
    category = (str(cat).lower() if cat else None) or (cats[0] if cats else None) or (tags[0] if tags else None)
    title, outcome = _first(m, "title", "question", default=""), m.get("outcome")
    ev_title = _first(event, "title", default=None)
    question = title or ev_title or m.get("slug", "")
    if ev_title and ev_title.lower() not in question.lower():
        question = f"{ev_title}: {question}"
    rules = "\n\n".join(x for x in (_first(m, "description", "rules", default=""),
                                    _first(event, "description", default="")) if x).strip()
    end = _first(m, "endDate", "endTime", "closeTime", "expirationTime", default=None) or \
        _first(event, "endTime", "endDate", default=None)
    return Market(
        market_id=str(m.get("slug") or m.get("id")), question=question, rules=rules,
        event_id=_first(m, "eventSlug", default=None) or event.get("slug"), event_title=ev_title,
        category=category, tags=sorted(set(tags + cats)), end_ts=parse_time(end),
        active=bool(m.get("active", True)), closed=bool(m.get("closed", False)),
        liquidity=_num(m.get("liquidity")), volume=_num(m.get("volume")), outcome=outcome,
        n_event_markets=len(event.get("markets") or []) or 1, raw={"market": m, "event": {k: v for k, v in event.items() if k != "markets"}})


def book_from_json(slug: str, data: dict, now: float | None = None) -> tuple[Book, Book, str | None]:
    """The venue's single (long-side) book -> (YES book, mirrored NO book, market state)."""
    md = data.get("marketData", data) or {}

    def levels(key):
        out = []
        for lv in md.get(key) or []:
            px, qty = _num(lv.get("px")), _num(lv.get("qty"))
            if px is not None and qty is not None and 0.0 < px < 1.0 and qty > 0:
                out.append((px, qty))
        return out

    bids, offers = levels("bids"), levels("offers")
    ts = now or time.time()
    yes = Book.from_levels(f"{slug}:YES", bids, offers, ts=ts)
    no = Book.from_levels(f"{slug}:NO", [(round(1.0 - p, 6), q) for p, q in offers],
                          [(round(1.0 - p, 6), q) for p, q in bids], ts=ts)
    return yes, no, md.get("state")


class PolymarketUS:
    """Read-only adapter. `client` is a polymarket_us.PolymarketUS() or anything shaped like it."""

    name = "polymarket_us"

    def __init__(self, client=None, min_interval: float = 0.5, clock=time.time):
        self.clock = clock                          # stamps order book snapshots; replaced in tests
        if client is None:
            from polymarket_us import PolymarketUS as _SDK      # imported here so tests need no SDK
            client = _SDK()
        self.client = client
        self.min_interval = float(min_interval)    # seconds between requests: slow on purpose
        self._last = 0.0
        self.requests = 0

    def _throttle(self) -> None:
        wait = self._last + self.min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        self.requests += 1

    def list_markets(self, max_events: int = 300, page: int = 50, **filters) -> list[Market]:
        """Open markets, via the events listing (each event carries its markets)."""
        out: list[Market] = []
        offset = 0
        while offset < max_events:
            self._throttle()
            params = {"limit": page, "offset": offset, "active": True, "closed": False, **filters}
            events = (self.client.events.list(params) or {}).get("events") or []
            for ev in events:
                for m in ev.get("markets") or []:
                    if m.get("closed") or m.get("active") is False:
                        continue
                    out.append(market_from_json(m, ev))
            if len(events) < page:
                break
            offset += page
        return out

    def market(self, slug: str) -> Market | None:
        """Full detail of one market (rules text), with its event when the market names one."""
        self._throttle()
        m = (self.client.markets.retrieve_by_slug(slug) or {}).get("market")
        if not m:
            return None
        ev = None
        if m.get("eventSlug"):
            try:
                self._throttle()
                ev = (self.client.events.retrieve_by_slug(m["eventSlug"]) or {}).get("event")
            except Exception:
                ev = None
        return market_from_json(m, ev)

    def is_closed(self, slug: str) -> bool:
        """One request: has this market closed? Used to look up resolutions of markets no longer being tracked."""
        self._throttle()
        m = (self.client.markets.retrieve_by_slug(slug) or {}).get("market") or {}
        return bool(m.get("closed"))

    def books(self, slug: str) -> tuple[Book, Book, str | None]:
        self._throttle()
        return book_from_json(slug, self.client.markets.book(slug) or {}, now=self.clock())

    def settlement(self, slug: str) -> float | None:
        """Payout of the long (YES) side once the market has settled: 1.0, 0.0, or in between. None = not settled."""
        self._throttle()
        try:
            s = self.client.markets.settlement(slug) or {}
        except Exception as e:                      # the SDK raises NotFoundError before settlement
            if getattr(e, "status_code", None) in (404, 400) or type(e).__name__ == "NotFoundError":
                return None
            raise
        v = _num(s.get("settlement"))
        if v is None:
            return None
        return v / 100.0 if v > 1.0 else v
