"""Which markets are worth a forecast. Rules only, no model: a forecast costs time and money, so the cheap checks
run first and most markets never reach Claude.

The filters come from the research (reports/): the retail accounts that lose are takers in longshots, short-dated
crypto and sports; the documented insider cases cluster in announcement, award and military markets; and "mention"
markets are a specialist game. What is left is mid-priced, reasonably liquid markets that resolve from a public,
objective source some days to weeks away, which is also where the evidence for language-model forecasts is least
bad.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .book import Book
from .venue import Market

DEFAULTS = {
    "min_days_to_resolution": 3.0,
    "max_days_to_resolution": 75.0,
    # Two tiers, because the exchange's non-sports markets are thin (live, 2026-11-18: of 95 tightly quoted
    # candidates the median had $1 resting within 2 cents of the price and $48 traded in total).
    #   forecast tier: enough of a market to have a price worth scoring a forecast against
    #   trade tier:    enough behind the price that a small order is not most of the book
    "min_volume": 0.0,                  # dollars traded in the market so far (from the order book's statistics)
    "min_depth_usd": 5.0,               # dollars resting within depth_band of the best price, thinner side
    "trade_min_volume": 1000.0,
    "trade_min_depth_usd": 50.0,
    "forecast_untradable": True,        # forecast markets that pass the first tier only (scored, never traded)
    "max_books_per_cycle": 60,         # order books read per cycle to rank candidates
    "depth_band": 0.02,
    "max_spread": 0.04,
    "price_range": [0.15, 0.85],
    # Categories as the exchange names them (seen live 2026-11-18: sports, politics, culture, macro, technology,
    # crypto, finance, geopolitics, science, climate). The allow list is also sent to the exchange, so the
    # thousands of sports events are never downloaded. Empty allow list = everything not denied.
    "categories_allow": ["economics", "politics", "elections", "companies", "science and technology", "health", "world"],
    "categories_deny": ["sports", "esports", "crypto", "financials", "commodities", "entertainment", "culture",
                        "climate and weather", "climate", "weather", "mentions"],
    # Title patterns (regular expressions, case-insensitive) that drop a market whatever its category.
    "title_deny": [
        r"\bup or down\b", r"\b(5|15|30)[- ]?min", r"\bhourly\b",                       # short-dated price bets
        r"\b(say|says|mention|mentions|tweet|tweets|post|posts)\b",                   # mention markets
        r"\b(nobel|oscar|oscars|grammy|emmy|golden globe|ballon d'or|person of the year|time 100)\b",  # leak-prone awards
        r"\b(strike|strikes|invade|invasion|airstrike|missile|troops|nuclear test|ceasefire)\b",      # military / insider-prone
        r"\b(resign|resigns|fired|step down|steps down|out as|announced out|out of (their|his|her)|leave office|leaves office|pardon|pardons|nominate|nominee)\b",  # personnel decisions
        # the forecaster does not bet on its own maker, nor on how AI models and their makers rank against each other
        r"\b(anthropic|claude|openai|chatgpt|gpt-?\d|gemini|grok|llm)\b|\bai (coding )?model\b|\bai company\b|\b(best|top) ai\b",
        r"\b(acquire|acquires|acquisition|merger|merge with|ipo|buyback)\b",                        # corporate announcements
    ],
    "max_markets_per_event": 2,
    "max_events_scanned": 2000,
    "max_candidates_per_cycle": 4,
    "reforecast_after_hours": 48.0,
}


def settings(cfg: dict | None) -> dict:
    given = (cfg or {}).get("universe") or {}
    unknown = sorted(set(given) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"unknown universe setting(s) in config: {', '.join(unknown)}")
    out = dict(DEFAULTS)
    out.update(given)
    return out


@dataclass
class Screen:
    market: Market
    ok: bool
    reason: str = ""
    yes: Book | None = None
    no: Book | None = None


def prefilter(m: Market, st: dict, now: float | None = None) -> str:
    """Reason to drop a market from its listing data alone ('' = keep)."""
    now = now or time.time()
    if m.closed or not m.active:
        return "closed or inactive"
    if m.status and m.status != "MARKET_STATUS_OPEN":
        return f"market status {m.status}"
    days = m.days_to_end(now)
    if days is None:
        return "no end date"
    if days < st["min_days_to_resolution"]:
        return f"{days:.1f} days to resolution (min {st['min_days_to_resolution']:g})"
    if days > st["max_days_to_resolution"]:
        return f"{days:.0f} days to resolution (max {st['max_days_to_resolution']:g})"
    labels = set(m.tags) | ({m.category} if m.category else set())
    if not labels:                                  # the deny list cannot be applied to a market with no label
        return "no category or tags"
    deny = {c.lower() for c in st["categories_deny"]}
    allow = {c.lower() for c in st["categories_allow"]}
    hit = labels & deny
    if hit:
        return f"category {sorted(hit)[0]} is excluded"
    if allow and not labels & allow:
        return "category not in the allow list"
    text = f"{m.question} {m.event_title or ''}"
    for pat in st["title_deny"]:
        if re.search(pat, text, flags=re.IGNORECASE):
            return f"title matches excluded pattern {pat!r}"
    if m.raw.get("lite"):                           # listing rows carry quotes: drop the hopeless ones for free
        if m.best_bid is None or m.best_ask is None:
            return "no two-sided quote"
        if m.best_ask - m.best_bid > st["max_spread"] + 1e-9:
            return f"spread {m.best_ask - m.best_bid:.3f} wider than {st['max_spread']:.3f}"
        lo, hi = st["price_range"]
        if not lo <= (m.best_bid + m.best_ask) / 2.0 <= hi:
            return f"mid {(m.best_bid + m.best_ask) / 2.0:.3f} outside [{lo:.2f}, {hi:.2f}]"
    if len(m.rules.strip()) < 40 and not m.raw.get("lite"):
        return "no resolution rules text"
    return ""


def book_check(yes: Book, state: str | None, st: dict) -> str:
    """Reason to drop a market from its order book ('' = keep)."""
    if state and state != "MARKET_STATE_OPEN":
        return f"market state {state}"
    if yes.best_bid is None or yes.best_ask is None:
        return "one-sided or empty book"
    if yes.spread > st["max_spread"] + 1e-9:
        return f"spread {yes.spread:.3f} wider than {st['max_spread']:.3f}"
    lo, hi = st["price_range"]
    if not lo <= yes.mid <= hi:
        return f"mid {yes.mid:.3f} outside [{lo:.2f}, {hi:.2f}]"
    if yes.volume_usd is not None and yes.volume_usd < st["min_volume"]:
        return f"only ${yes.volume_usd:,.0f} traded so far (min ${st['min_volume']:,.0f})"
    near = yes.near_touch_usd(st["depth_band"])
    if near < st["min_depth_usd"]:
        return f"only ${near:.0f} resting near the best price (min ${st['min_depth_usd']:.0f})"
    return ""


def trade_check(yes: Book, st: dict) -> str:
    """Reason a market that is good enough to forecast is too thin to trade ('' = tradable)."""
    if (yes.volume_usd or 0.0) < st["trade_min_volume"]:
        return f"only ${yes.volume_usd or 0:,.0f} traded so far (trading needs ${st['trade_min_volume']:,.0f})"
    near = yes.near_touch_usd(st["depth_band"])
    if near < st["trade_min_depth_usd"]:
        return f"only ${near:.0f} resting near the best price (trading needs ${st['trade_min_depth_usd']:.0f})"
    return ""


def choose(markets: list[Market], cfg: dict | None, last_forecast_ts: dict[str, float], held: set[str],
           now: float | None = None) -> tuple[list[Market], dict[str, str]]:
    """Order the markets that pass the listing filters and are due a forecast. Held markets come first (their
    forecasts must stay fresh), then never-forecast markets with the tightest quotes, at most max_markets_per_event from any
    one event. Returns (candidates in order, dropped market_id -> reason). The caller checks books and stops at
    max_candidates_per_cycle."""
    st = settings(cfg)
    now = now or time.time()
    dropped: dict[str, str] = {}
    keep: list[Market] = []
    for m in markets:
        why = prefilter(m, st, now)
        if why and m.market_id not in held:
            dropped[m.market_id] = why
            continue
        last = last_forecast_ts.get(m.market_id)
        if last is not None and now - last < st["reforecast_after_hours"] * 3600.0:
            dropped[m.market_id] = "forecast still fresh"
            continue
        keep.append(m)

    def key(m: Market):                             # held, then never forecast, then the tightest quotes, then soonest
        spread = (m.best_ask - m.best_bid) if m.best_bid is not None and m.best_ask is not None else 1.0
        return (0 if m.market_id in held else 1, 0 if m.market_id not in last_forecast_ts else 1,
                round(spread, 4), m.end_ts or 0.0, m.market_id)

    keep.sort(key=key)
    per_event: dict[str, int] = {}
    out = []
    for m in keep:
        ev = m.event_id or m.market_id
        if m.market_id not in held and per_event.get(ev, 0) >= st["max_markets_per_event"]:
            dropped[m.market_id] = "event already has enough candidates this cycle"
            continue
        per_event[ev] = per_event.get(ev, 0) + 1
        out.append(m)
    return out, dropped
