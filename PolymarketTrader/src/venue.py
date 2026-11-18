"""Market data from Polymarket US, the CFTC-regulated venue open to US residents (gateway.polymarket.us).

Everything here is a public, read-only GET: no keys, no account. The official `polymarket-us` SDK is used when it
is installed; any object with the same `events` / `markets` methods works, which is how the tests run offline.

How the venue models a market (checked against the live API on 2026-11-18; tests/fixtures holds real payloads):
  - a market is identified by its `slug` and belongs to an event; a multi-outcome event ("CPI in November") is a
    set of separate yes/no markets ("Above 3.6%")
  - there is ONE order book per market, quoted for the "long" side, which is YES (`marketSides[].long`). Buying
    NO is a "short" order. The NO book is therefore the YES book mirrored: NO ask = 1 - YES bid.
  - prices are {"value": "0.55", "currency": "USD"}; quantities are strings of contracts
  - each market carries its own tick size (`orderPriceMinTickSize`: 0.01 for most, down to 0.001), minimum
    quantity (`minimumTradeQty`), fee coefficient (`feeCoefficient`), end date, category and rules (`description`)
  - listings carry no liquidity or volume figure; traded dollars and open interest come with the order book
  - `GET /settlement` answers 404 until a market has settled, then {"settlement": 0 or 1}: the YES payout

The API returns more fields than the SDK's types declare, so everything is read defensively: several spellings,
missing = None, and a market without an end date, rules or category is simply not traded.
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
    status: str | None = None           # e.g. MARKET_STATUS_OPEN
    tick: float | None = None           # price increment for this market
    min_qty: float | None = None        # smallest order, in contracts
    fee_rate: float | None = None       # taker fee coefficient for this market
    maker_fee_rate: float | None = None # maker fee coefficient (0 or None on most markets)
    open_interest: float | None = None  # contracts outstanding, where the listing gives it
    best_bid: float | None = None       # quotes as shown in the listing (may be seconds stale)
    best_ask: float | None = None
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
                "end_ts": self.end_ts, "yes_token": self.yes_token, "no_token": self.no_token,
                "fee_rate": self.fee_rate, "maker_fee_rate": self.maker_fee_rate}


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


def is_rate_limit(e: Exception) -> bool:
    return getattr(e, "status_code", None) == 429 or type(e).__name__ == "RateLimitError"


def brief(e: Exception, n: int = 140) -> str:
    """An exception as one short line. Error pages from the gateway are whole HTML documents."""
    text = " ".join(str(e).split())
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        text = "HTML error page"
    return f"{type(e).__name__}: {text[:n]}"


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
    title = _first(m, "title", "question", default="")
    long_side = next((x for x in m.get("marketSides") or [] if isinstance(x, dict) and x.get("long")), None)
    outcome = (long_side or {}).get("description") or m.get("outcome")
    ev_title = _first(event, "title", default=None) or (m.get("question") if m.get("question") != title else None)
    question = title or ev_title or m.get("slug", "")
    if ev_title and ev_title.lower() not in question.lower():
        question = f"{ev_title}: {question}"
    insider = event.get("insiderTradingRules")
    rules = "\n\n".join(str(x) for x in (_first(m, "description", "rules", default=""),
                                         _first(event, "description", default=""),
                                         f"Insider trading rules: {insider}" if insider else "") if x).strip()
    end = _first(m, "endDate", "endTime", "closeTime", "expirationTime", default=None) or \
        _first(event, "endDate", "endTime", default=None)
    status = m.get("status")
    resolved = bool(m.get("closed", False)) or status in ("MARKET_STATUS_RESOLVED", "MARKET_STATUS_CLOSED")
    return Market(
        market_id=str(m.get("slug") or m.get("id")), question=question, rules=rules,
        event_id=_first(m, "eventSlug", default=None) or event.get("slug"), event_title=ev_title,
        category=category, tags=sorted(set(tags + cats)), end_ts=parse_time(end),
        active=bool(m.get("active", True)), closed=resolved, status=status,
        liquidity=_num(m.get("liquidity")), volume=_num(m.get("volume")), outcome=outcome,
        tick=_num(m.get("orderPriceMinTickSize")), min_qty=_num(m.get("minimumTradeQty")),
        fee_rate=_num(m.get("feeCoefficient")),
        best_bid=_num(m.get("bestBidQuote")), best_ask=_num(m.get("bestAskQuote")),
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
    stats = md.get("stats") or {}
    for book in (yes, no):
        book.volume_usd, book.open_interest = _num(stats.get("notionalTraded")), _num(stats.get("openInterest"))
    return yes, no, md.get("state")


class PolymarketUS:
    """Read-only adapter. `client` is a polymarket_us.PolymarketUS() or anything shaped like it."""

    name = "polymarket_us"

    def __init__(self, client=None, min_interval: float = 1.0, clock=time.time, rate_limit_pause: float = 30.0):
        self.clock = clock                          # stamps order book snapshots; replaced in tests
        if client is None:
            from polymarket_us import PolymarketUS as _SDK      # imported here so tests need no SDK
            client = _SDK()
        self.client = client
        self.min_interval = float(min_interval)    # seconds between requests: slow on purpose
        self.rate_limit_pause = float(rate_limit_pause)
        self.rate_limited = 0
        self._last = 0.0
        self.requests = 0

    def _throttle(self) -> None:
        wait = self._last + self.min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        self.requests += 1

    def _call(self, fn, *args):
        """One request, paced. The public gateway rate-limits (seen live: an HTTP 429 after a burst of order-book
        reads). On a rate limit: wait, slow down for the rest of the cycle, try once more, then give up."""
        self._throttle()
        try:
            return fn(*args)
        except Exception as e:
            if not is_rate_limit(e):
                raise
            self.rate_limited += 1
            self.min_interval = min(max(self.min_interval * 2.0, 1.0), 8.0)
            time.sleep(self.rate_limit_pause)
            self._throttle()
            return fn(*args)

    def list_markets(self, max_events: int = 2000, page: int = 100, categories: list[str] | None = None,
                     min_days: float | None = None, max_days: float | None = None, **filters) -> list[Market]:
        """Open markets, via the events listing (each event carries its markets). `categories` is applied by the
        exchange: the full listing is thousands of events, most of them sports."""
        out: list[Market] = []
        offset = 0
        if categories:
            filters = {**filters, "categories": list(categories)}
        while offset < max_events:
            params = {"limit": min(page, max_events - offset), "offset": offset, "active": True, "closed": False, **filters}
            events = (self._call(self.client.events.list, params) or {}).get("events") or []
            for ev in events:
                for m in ev.get("markets") or []:
                    mk = market_from_json(m, ev)
                    if mk.closed or not mk.active:
                        continue
                    out.append(mk)
            if len(events) < params["limit"]:
                break
            offset += page
        return out

    def market(self, slug: str) -> Market | None:
        """Full detail of one market (rules text), with its event when the market names one."""
        m = (self._call(self.client.markets.retrieve_by_slug, slug) or {}).get("market")
        if not m:
            return None
        ev = None
        if m.get("eventSlug"):
            try:
                ev = (self._call(self.client.events.retrieve_by_slug, m["eventSlug"]) or {}).get("event")
            except Exception:
                ev = None
        return market_from_json(m, ev)

    def enrich(self, listed: Market) -> Market | None:
        """Fresh detail for a market that came from the listing, keeping what only the listing knows (its event:
        the detail endpoint does not name it)."""
        full = self.market(listed.market_id)
        if full is None:
            return None
        full.event_id = full.event_id or listed.event_id
        full.event_title = full.event_title or listed.event_title
        full.question = listed.question or full.question         # the listing's "event: outcome" wording
        full.tags = sorted(set(full.tags) | set(listed.tags))
        full.category = full.category or listed.category
        full.n_event_markets = max(full.n_event_markets, listed.n_event_markets)
        if listed.rules and listed.rules not in full.rules:
            extra = [part for part in listed.rules.split("\n\n") if part and part not in full.rules]
            full.rules = "\n\n".join([full.rules] + extra).strip()
        return full

    def is_closed(self, slug: str) -> bool:
        """One request: has this market closed? Used to look up resolutions of markets no longer being tracked."""
        m = (self._call(self.client.markets.retrieve_by_slug, slug) or {}).get("market") or {}
        return market_from_json(m).closed

    def books(self, slug: str) -> tuple[Book, Book, str | None]:
        return book_from_json(slug, self._call(self.client.markets.book, slug) or {}, now=self.clock())

    def settlement(self, slug: str) -> float | None:
        """Payout of the long (YES) side once the market has settled: 1.0, 0.0, or in between. None = not settled."""
        try:
            s = self._call(self.client.markets.settlement, slug) or {}
        except Exception as e:                      # the SDK raises NotFoundError before settlement
            if getattr(e, "status_code", None) in (404, 400) or type(e).__name__ == "NotFoundError":
                return None
            raise
        v = _num(s.get("settlement"))
        if v is None:
            return None
        return v / 100.0 if v > 1.0 else v
