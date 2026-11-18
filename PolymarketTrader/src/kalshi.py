"""Market data from Kalshi, the CFTC-regulated exchange (api.elections.kalshi.com). Same interface as the
Polymarket US adapter in venue.py, so the trader does not care which one it is given.

Everything here is a public, read-only GET: no account, no key. Checked against the live API on 2026-11-18;
tests/fixtures/kalshi_cpi_yoy.json holds real payloads.

How Kalshi models a market:
  - a market has a `ticker` and belongs to an event (`event_ticker`), which belongs to a series ("CPI
    year-over-year"). The category (Economics, Politics, ...) and the fee type live on the series.
  - prices are dollar strings ("0.8000"); quantities are contract strings and may be fractional ("15156.15")
  - the order book lists resting BIDS only, for YES and for NO. A YES ask is a NO bid seen from the other side:
    YES ask = 1 - best NO bid.
  - a settled market has `result` "yes" or "no" (and `settlement_value_dollars`)
  - taker fee per contract = 0.07 x multiplier x p x (1 - p); series of type "quadratic_with_maker_fees" also
    charge makers a quarter of that

Listing is the expensive part: Kalshi has about 180,000 open markets, more than half of them sports, and no
category filter. The adapter asks only for markets closing inside the wanted window, reads the answer a page at a
time, keeps the few that belong to an allowed category and have a two-sided quote, and forgets the rest, so it
never holds more than one page (about 2 MB) in memory.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .book import Book
from .kalshi_http import KalshiError, KalshiHTTP
from .venue import Market, _num, parse_time

TAKER_RATE = 0.07
MAKER_RATE = 0.0175                                 # only on series whose fee type includes maker fees
OPEN_STATUSES = {"active", "open"}


def series_of(event_ticker: str | None) -> str:
    return (event_ticker or "").split("-")[0]


def market_from_kalshi(m: dict, series_info: dict | None = None, event: dict | None = None) -> Market:
    """One Kalshi market (listing or detail shape, they match) -> Market."""
    info = series_info or {}
    event = event or {}
    title = (m.get("title") or "").strip()
    sub = (m.get("yes_sub_title") or "").strip()
    ev_title = (event.get("title") or "").strip() or None
    question = title or f"{ev_title or m.get('ticker')}"
    if sub and sub.lower() not in question.lower() and sub.lower() not in ("yes", "no"):
        question = f"{question} [{sub}]"            # which outcome of the event this market is about
    rules = "\n\n".join(x.strip() for x in (m.get("rules_primary") or "", m.get("rules_secondary") or "",
                                            m.get("early_close_condition") or "") if x and x.strip())
    sources = [f"{s.get('name')} ({s.get('url')})" for s in event.get("settlement_sources") or [] if s.get("name")]
    if sources:
        rules += "\n\nSettlement sources named by the exchange: " + "; ".join(sources[:8])
    status = m.get("status")
    result = m.get("result") or ""
    ranges = m.get("price_ranges") or []
    mult = _num(info.get("fee_multiplier"))
    mult = 1.0 if mult is None else mult
    bid, ask = _num(m.get("yes_bid_dollars")), _num(m.get("yes_ask_dollars"))
    if bid is not None and bid <= 0:
        bid = None                                  # Kalshi reports "no bid" as 0 and "no ask" as 1
    if ask is not None and ask >= 1:
        ask = None
    mid = (bid + ask) / 2.0 if bid is not None and ask is not None else _num(m.get("last_price_dollars"))
    vol = _num(m.get("volume_fp"))
    category = (info.get("category") or event.get("category") or "").lower() or None
    mk = Market(
        market_id=str(m.get("ticker")), question=question, rules=rules,
        event_id=m.get("event_ticker"), event_title=ev_title, category=category,
        tags=sorted({t.lower() for t in (info.get("tags") or []) if t} | ({category} if category else set())),
        end_ts=parse_time(m.get("close_time")), active=status in OPEN_STATUSES,
        closed=status not in OPEN_STATUSES or result in ("yes", "no"), status="MARKET_STATUS_OPEN" if status in OPEN_STATUSES else status,
        volume=None if vol is None or mid is None else vol * mid, outcome=sub or "Yes",
        tick=_num(ranges[0].get("step")) if ranges else 0.01, min_qty=0.01,
        fee_rate=TAKER_RATE * mult,
        best_bid=bid, best_ask=ask, raw={"market": {k: m.get(k) for k in ("ticker", "event_ticker", "status", "result", "close_time",
                                                                          "open_interest_fp", "volume_24h_fp", "market_type")}})
    mk.maker_fee_rate = MAKER_RATE * mult if "maker" in str(info.get("fee_type") or "") else 0.0
    mk.open_interest = _num(m.get("open_interest_fp"))
    return mk


def books_from_kalshi(ticker: str, data: dict, now: float | None = None) -> tuple[Book, Book]:
    ob = data.get("orderbook_fp") or data.get("orderbook") or {}

    def levels(*keys):
        for key in keys:
            raw = ob.get(key)
            if raw:
                out = []
                for lv in raw:
                    p, q = _num(lv[0]), _num(lv[1])
                    if p is not None and q is not None and q > 0:
                        if key in ("yes", "no"):    # the older shape quotes cents
                            p = p / 100.0
                        if 0.0 < p < 1.0:
                            out.append((p, q))
                return out
        return []

    yes_bids, no_bids = levels("yes_dollars", "yes"), levels("no_dollars", "no")
    ts = now or time.time()
    yes = Book.from_levels(f"{ticker}:YES", yes_bids, [(round(1.0 - p, 6), q) for p, q in no_bids], ts=ts)
    no = Book.from_levels(f"{ticker}:NO", no_bids, [(round(1.0 - p, 6), q) for p, q in yes_bids], ts=ts)
    return yes, no


class Kalshi:
    name = "kalshi"

    def __init__(self, http: KalshiHTTP | None = None, min_interval: float = 1.0, clock=time.time,
                 cache_dir: str | Path | None = None, series_cache_hours: float = 24.0, listing_cache_hours: float = 20.0):
        self.http = http or KalshiHTTP(min_interval=min_interval)
        self.clock = clock
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.series_cache_hours = float(series_cache_hours)
        self.listing_cache_hours = float(listing_cache_hours)
        self.listing_partial = False                # True when the last scan was cut off by throttling
        self._series: dict[str, dict] = {}          # series ticker -> {category, fee_type, fee_multiplier, tags}
        self._series_cats: set[str] = set()
        self._seen: dict[str, Market] = {}          # markets met this run: volume and fees for books()

    @property
    def requests(self) -> int:
        return self.http.requests

    @property
    def rate_limited(self) -> int:
        return self.http.rate_limited

    # ---- series: category and fees ------------------------------------------------
    def _load_series(self, categories: list[str]) -> None:
        """Series of the wanted categories. One request per category; kept on disk for a day."""
        want = [c for c in categories if c.lower() not in self._series_cats]
        if not want:
            return
        cache = self.cache_dir / "kalshi_series.json" if self.cache_dir else None
        stored = {}
        if cache and cache.exists() and time.time() - cache.stat().st_mtime < self.series_cache_hours * 3600:
            try:
                stored = json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                stored = {}
        for cat in want:
            rows = stored.get(cat.lower())
            if rows is None:
                rows = [{"ticker": s.get("ticker"), "fee_type": s.get("fee_type"), "fee_multiplier": s.get("fee_multiplier"),
                         "tags": s.get("tags") or []}
                        for s in self.http.get("/series", category=cat).get("series") or []]
                stored[cat.lower()] = rows
            for s in rows:
                self._series[s["ticker"]] = {**s, "category": cat}
            self._series_cats.add(cat.lower())
        if cache:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(stored), encoding="utf-8")
            except OSError:
                pass

    def _info(self, event_ticker: str | None) -> dict | None:
        return self._series.get(series_of(event_ticker))

    # ---- listing ---------------------------------------------------------------------
    KEEP = ("ticker", "event_ticker", "status", "result", "title", "yes_sub_title", "close_time", "yes_bid_dollars",
            "yes_ask_dollars", "last_price_dollars", "volume_fp", "open_interest_fp", "price_ranges", "market_type")

    def list_markets(self, max_events: int = 2000, categories: list[str] | None = None, min_days: float = 0.0,
                     max_days: float = 400.0, max_pages: int = 400, **_ignored) -> list[Market]:
        """Open binary markets of the wanted categories closing between min_days and max_days from now, with a
        two-sided quote. Categories are matched without regard to case; Kalshi's own names are, for example,
        "Economics", "Politics", "Companies", "Commodities", "Science and Technology".

        The full listing is about 150 requests, and Kalshi throttles them. So the result is kept on disk and
        reused for `listing_cache_hours`; a scan that is cut off keeps what it has and carries on from the same
        place next time. Listed quotes can therefore be hours old: they only decide which order books to read,
        and every decision after that uses a fresh book and fresh market detail."""
        if not categories:
            raise ValueError("Kalshi needs an allow list of categories (universe.categories_allow): "
                             "listing everything means downloading about 180,000 markets")
        names = {c.lower(): c for c in ("Economics", "Financials", "Politics", "Elections", "Companies", "Commodities",
                                        "Science and Technology", "Climate and Weather", "Crypto", "Entertainment",
                                        "Mentions", "Health", "Social", "World", "Sports")}
        self._load_series([names.get(c.lower(), c) for c in categories])
        allowed = sorted(c.lower() for c in categories)
        now = self.clock()
        key = {"categories": allowed, "min_days": float(min_days), "max_days": float(max_days)}
        st = self._read_listing()
        fresh = st.get("key") == key and st.get("finished") and now - st["finished"] < self.listing_cache_hours * 3600
        resume = st.get("key") == key and not st.get("finished") and st.get("cursor") and now - st.get("started", 0) < 3 * 3600
        if not fresh:
            if not resume:
                st = {"key": key, "started": now, "finished": None, "cursor": None, "markets": [],
                      "lo": int(now + min_days * 86400), "hi": int(now + max_days * 86400)}
            self.listing_partial = False
            for _ in range(max_pages):
                try:
                    d = self.http.get("/markets", tries=4, limit=1000, cursor=st["cursor"], status="open",
                                      min_close_ts=st["lo"], max_close_ts=st["hi"])
                except KalshiError:
                    self.listing_partial = True         # throttled: keep what we have, carry on next time
                    break
                page = d.get("markets") or []
                for m in page:
                    if m.get("market_type") not in (None, "binary"):
                        continue
                    info = self._info(m.get("event_ticker"))
                    if info is None or info["category"].lower() not in allowed:
                        continue                        # sports and the rest are dropped here, a market at a time
                    if not (_num(m.get("yes_bid_dollars")) or 0) > 0 or not (_num(m.get("yes_ask_dollars")) or 1) < 1:
                        continue
                    st["markets"].append({k: m.get(k) for k in self.KEEP})
                st["cursor"] = d.get("cursor") or None
                if not st["cursor"] or not page:
                    st["finished"] = self.clock()
                    break
                self._write_listing(st)
            self._write_listing(st)
        out: list[Market] = []
        seen = set()
        for m in st["markets"]:
            if m["ticker"] in seen:
                continue
            seen.add(m["ticker"])
            mk = market_from_kalshi(m, self._info(m.get("event_ticker")))
            days = mk.days_to_end(now)
            if mk.closed or mk.best_bid is None or mk.best_ask is None or days is None or days < 0:
                continue
            out.append(mk)
            self._seen[mk.market_id] = mk
        return out

    def _read_listing(self) -> dict:
        path = self.cache_dir / "kalshi_listing.json" if self.cache_dir else None
        if path is None:
            return getattr(self, "_listing_mem", {})
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_listing(self, st: dict) -> None:
        self._listing_mem = st
        if self.cache_dir:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                tmp = self.cache_dir / "kalshi_listing.json.tmp"
                tmp.write_text(json.dumps(st), encoding="utf-8")
                tmp.replace(self.cache_dir / "kalshi_listing.json")
            except OSError:
                pass

    # ---- one market ---------------------------------------------------------------------
    def _detail(self, ticker: str) -> dict | None:
        try:
            return (self.http.get(f"/markets/{ticker}") or {}).get("market")
        except KalshiError as e:
            if e.status_code == 404:
                return None
            raise

    def market(self, ticker: str) -> Market | None:
        m = self._detail(ticker)
        if not m:
            return None
        if self._info(m.get("event_ticker")) is None:
            try:                                    # a held market whose category was not loaded this run
                s = (self.http.get(f"/series/{series_of(m.get('event_ticker'))}") or {}).get("series") or {}
                self._series[s.get("ticker") or series_of(m.get("event_ticker"))] = {
                    "ticker": s.get("ticker"), "fee_type": s.get("fee_type"), "fee_multiplier": s.get("fee_multiplier"),
                    "tags": s.get("tags") or [], "category": s.get("category") or ""}
            except KalshiError:
                pass
        mk = market_from_kalshi(m, self._info(m.get("event_ticker")))
        self._seen[mk.market_id] = mk
        return mk

    def enrich(self, listed: Market) -> Market | None:
        """Fresh status and quotes, plus what only the event knows: its title and the named settlement sources."""
        m = self._detail(listed.market_id)
        if not m:
            return None
        event = {}
        try:
            event = (self.http.get(f"/events/{m.get('event_ticker')}") or {}).get("event") or {}
        except KalshiError:
            event = {}
        mk = market_from_kalshi(m, self._info(m.get("event_ticker")), event)
        mk.n_event_markets = listed.n_event_markets
        self._seen[mk.market_id] = mk
        return mk

    def is_closed(self, ticker: str) -> bool:
        m = self._detail(ticker)
        return bool(m) and market_from_kalshi(m).closed

    def books(self, ticker: str) -> tuple[Book, Book, str | None]:
        yes, no = books_from_kalshi(ticker, self.http.get(f"/markets/{ticker}/orderbook") or {}, now=self.clock())
        known = self._seen.get(ticker)
        for book in (yes, no):
            book.volume_usd = known.volume if known else None
            book.open_interest = getattr(known, "open_interest", None) if known else None
        return yes, no, None

    def settlement(self, ticker: str) -> float | None:
        """YES payout once the market has a result: 1.0 for "yes", 0.0 for "no"; any other settled value as
        reported (the trader refuses to settle on anything but 0, 0.5 or 1). None = not settled yet."""
        m = self._detail(ticker)
        if not m:
            return None
        if m.get("result") == "yes":
            return 1.0
        if m.get("result") == "no":
            return 0.0
        if m.get("status") in ("finalized", "settled", "determined"):
            return _num(m.get("settlement_value_dollars"))
        return None
