"""Watch one mechanical rule on the live exchange without trading it, on paper or otherwise.

The rule (reports/2026-11-18_strategy_research.md, section 3.7): in a market that has already traded a lot, when
YES is quoted at 5 cents or less with a spread of 5 cents or less and the market ends within 30 days, buy NO.
The backtest says what such bets paid. It cannot say how many contracts were really on offer at that price,
because Kalshi's history has prices and volume but no order books. This script answers that going forward:

    python scripts/shadow_longshot.py            look at up to 25 new candidates, check finished ones
    python scripts/shadow_longshot.py --report   what has been seen so far

For every qualifying market it records, once: the quote, the contracts resting at the NO ask and within a cent of
it, and what a $20 order would have paid on that book (half of the displayed size assumed real, fee rounded up
to the cent). Later it records how the market settled. Nothing is ordered and the paper account is not touched:
the observations live in their own file, data/shadow.db.

It also answers the question the backtest's resting orders depend on (report 3.13): would a small resting NO bid
really have been filled? At the observation it notes the best NO bid and how many contracts were already queued
there. Over the next three days it reads the exchange's public trades and counts the order as filled only if
buyers of YES traded through that price, or took at least everything queued ahead plus the order itself.
"""
import argparse
import json
import math
import sqlite3
import sys
import time
import zlib

from _bootstrap import ROOT

from src.book import simulate_buy, summarize
from src.kalshi import Kalshi, market_from_kalshi, books_from_kalshi
from src.kalshi_http import KalshiError
from src.venue import parse_time

SCHEMA = """
CREATE TABLE IF NOT EXISTS obs (ticker TEXT PRIMARY KEY, event TEXT, category TEXT, title TEXT, seen_ts REAL, end_ts REAL,
    early INTEGER, yes_bid REAL, yes_ask REAL, no_ask REAL, ask_contracts REAL, ask_usd_1c REAL, volume REAL,
    stake REAL, fill_px REAL, fill_shares REAL, fee REAL, result TEXT, settled_ts REAL);
CREATE TABLE IF NOT EXISTS checked (ticker TEXT PRIMARY KEY, ts REAL, why TEXT);
"""
# added later: the hypothetical resting NO bid and what became of it
EXTRA = {"rest_px": "REAL", "rest_ahead": "REAL", "maker_rate": "REAL", "rest_filled": "INTEGER", "rest_fill_ts": "REAL",
         "rest_done": "INTEGER"}
REST_HOURS = 72.0           # the backtest leaves a resting order for three daily bars


def open_db(db):
    db.executescript(SCHEMA)
    have = {r[1] for r in db.execute("PRAGMA table_info(obs)")}
    for col, kind in EXTRA.items():
        if col not in have:
            db.execute(f"ALTER TABLE obs ADD COLUMN {col} {kind}")
    db.execute("UPDATE obs SET rest_px = 1 - yes_ask WHERE rest_px IS NULL")       # rows from before the columns existed
    db.commit()
    return db
RULE = {"max_mid": 0.05, "max_spread": 0.05, "max_days": 30.0, "min_days": 0.25}


def order_fee(rate: float, price: float, shares: float) -> float:
    """Kalshi's taker fee on one order: rate x contracts x p x (1 - p), rounded up to the cent."""
    return math.ceil(rate * shares * price * (1 - price) * 100 - 1e-9) / 100.0


def candidates(listing: dict, categories: set[str], category_of, min_volume: float, skip: set[str], now: float) -> list[dict]:
    """Listed markets that might qualify, in a fixed pseudo-random order (not biggest first: that would make the
    observations a picture of the busiest markets only)."""
    out = []
    for m in listing.get("markets") or []:
        try:
            bid, ask, vol = float(m["yes_bid_dollars"]), float(m["yes_ask_dollars"]), float(m.get("volume_fp") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if m["ticker"] in skip or bid <= 0 or ask >= 1 or vol < min_volume:
            continue
        if (bid + ask) / 2 > RULE["max_mid"] + 0.03:            # listed quotes are hours old: a loose first cut
            continue
        end = parse_time(m.get("close_time"))
        if end is None or not RULE["min_days"] < (end - now) / 86400.0 <= RULE["max_days"]:
            continue
        if category_of(m.get("event_ticker")) not in categories:
            continue
        out.append(m)
    out.sort(key=lambda m: zlib.crc32(m["ticker"].encode()))
    return out


def look(venue: Kalshi, db, m: dict, now: float, stake: float, min_volume: float) -> str:
    """Read one candidate's fresh detail and book; record it if the rule holds. Returns what happened."""
    ticker = m["ticker"]
    d = venue._detail(ticker)
    if not d:
        return "gone"
    mk = market_from_kalshi(d, venue._info(d.get("event_ticker")))
    end = parse_time(d.get("close_time"))
    days = (end - now) / 86400.0 if end else None
    vol = float(d.get("volume_fp") or 0)
    if mk.closed or days is None:
        return "closed"
    if not RULE["min_days"] < days <= RULE["max_days"]:
        return f"{days:.0f} days to the end"
    if vol < min_volume:
        return "volume below the tested level"
    yes, no = books_from_kalshi(ticker, venue.http.get(f"/markets/{ticker}/orderbook") or {}, now=now)
    if yes.best_bid is None or yes.best_ask is None:
        return "one-sided book"
    if yes.mid > RULE["max_mid"] + 1e-9 or yes.spread > RULE["max_spread"] + 1e-9:
        return f"mid {yes.mid:.3f}, spread {yes.spread:.3f}"
    ask = no.best_ask
    at_ask = sum(s for p, s in no.asks if p <= ask + 1e-9)
    near = sum(p * s for p, s in no.asks if p <= ask + 0.01 + 1e-9)
    fills = simulate_buy(no, stake, limit=min(ask + 0.01, 0.99), fee_per_share=lambda p: mk.fee_rate * p * (1 - p))
    shares, px, _ = summarize(fills)
    fee = order_fee(mk.fee_rate, px, shares) if shares else 0.0
    rest_px = no.best_bid                           # the price a resting NO order would join: 1 - the YES ask
    ahead = sum(q for p, q in no.bids if p >= rest_px - 1e-9) if rest_px else None
    db.execute("INSERT OR IGNORE INTO obs (ticker, event, category, title, seen_ts, end_ts, early, yes_bid, yes_ask, no_ask, "
               "ask_contracts, ask_usd_1c, volume, stake, fill_px, fill_shares, fee, rest_px, rest_ahead, maker_rate) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (ticker, d.get("event_ticker"), mk.category, mk.question[:200], now, end, 1 if d.get("can_close_early") else 0,
                yes.best_bid, yes.best_ask, ask, at_ask, near, vol, stake, px if shares else None, shares, fee,
                rest_px, ahead, getattr(mk, "maker_fee_rate", 0.0)))
    return "recorded"


def resting_fill(trades: list[dict], yes_ask: float, need: float | None) -> float | None:
    """When a resting NO bid at 1 - yes_ask would have been filled, or None. `need` = contracts queued ahead plus
    the order itself (None when the queue was not recorded: then only a trade THROUGH the price counts)."""
    at = 0.0
    for t in sorted(trades, key=lambda t: t.get("created_time") or ""):
        if t.get("taker_side") != "yes":            # only buyers of YES hit resting NO bids
            continue
        try:
            px, n = float(t["yes_price_dollars"]), float(t["count_fp"])
        except (KeyError, TypeError, ValueError):
            continue
        if px > yes_ask + 1e-9:                     # traded through: everything at our price is gone
            return parse_time(t.get("created_time"))
        if abs(px - yes_ask) <= 1e-9:
            at += n
            if need is not None and at >= need - 1e-9:
                return parse_time(t.get("created_time"))
    return None


def track_resting(venue: Kalshi, db, now: float, max_checks: int = 30) -> int:
    """For observations whose three-day window is still open or just closed: read the public trades since the
    observation and decide whether the resting NO bid would have been filled."""
    rows = db.execute("SELECT ticker, seen_ts, end_ts, yes_ask, rest_px, rest_ahead, stake FROM obs "
                      "WHERE COALESCE(rest_done, 0) = 0 ORDER BY seen_ts LIMIT ?", (max_checks,)).fetchall()
    decided = 0
    for ticker, seen, end, yes_ask, rest_px, ahead, stake in rows:
        until = min(seen + REST_HOURS * 3600, end or 9e18)
        try:
            trades = list(venue.http.pages("/markets/trades", "trades", max_pages=5, tries=3, ticker=ticker,
                                           min_ts=int(seen), max_ts=int(min(until, now))))
        except KalshiError as e:
            if e.status_code == 429:
                break
            continue
        need = None if ahead is None or not rest_px else ahead + stake / rest_px
        when = resting_fill(trades, yes_ask, need)
        if when is not None or now >= until:
            db.execute("UPDATE obs SET rest_filled=?, rest_fill_ts=?, rest_done=1 WHERE ticker=?",
                       (1 if when is not None else 0, when, ticker))
            decided += 1
    db.commit()
    return decided


def observe(venue: Kalshi, db, listing: dict, categories: set[str], now: float, max_new: int = 25, max_settle: int = 40,
            stake: float = 20.0, min_volume: float = 45000.0, recheck_hours: float = 24.0, per_event: int = 2) -> dict:
    open_db(db)
    out = {"recorded": 0, "looked": 0, "settled": 0, "resting_decided": 0}
    # 1. how did the finished ones settle?
    due = db.execute("SELECT ticker FROM obs WHERE result IS NULL AND end_ts < ? ORDER BY end_ts LIMIT ?", (now, max_settle)).fetchall()
    for (ticker,) in due:
        try:
            d = venue._detail(ticker) or {}
        except KalshiError:
            break
        if d.get("result") in ("yes", "no"):
            db.execute("UPDATE obs SET result=?, settled_ts=? WHERE ticker=?", (d["result"], now, ticker))
            out["settled"] += 1
    # 2. new candidates
    skip = {r[0] for r in db.execute("SELECT ticker FROM obs")}
    skip |= {r[0] for r in db.execute("SELECT ticker FROM checked WHERE ts > ?", (now - recheck_hours * 3600,))}
    per: dict[str, int] = {}
    info = lambda ev: ((venue._info(ev) or {}).get("category") or "").lower()          # noqa: E731
    for m in candidates(listing, categories, info, min_volume, skip, now):
        if out["looked"] >= max_new:
            break
        ev = m.get("event_ticker") or m["ticker"]
        if per.get(ev, 0) >= per_event:
            continue
        per[ev] = per.get(ev, 0) + 1
        try:
            what = look(venue, db, m, now, stake, min_volume)
        except KalshiError as e:
            what = f"error {e.status_code}"
            if e.status_code == 429:
                break
        out["looked"] += 1
        out["recorded"] += what == "recorded"
        db.execute("INSERT OR REPLACE INTO checked VALUES (?,?,?)", (m["ticker"], now, what))
        db.commit()
    db.commit()
    out["resting_decided"] = track_resting(venue, db, now)
    return out


def report(db) -> str:
    open_db(db)
    rows = db.execute("SELECT no_ask, ask_contracts, ask_usd_1c, fill_px, fill_shares, fee, stake, result, category FROM obs").fetchall()
    if not rows:
        return "no observations yet"

    def q(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(p * len(xs)))]

    at_ask = [a * c for a, c, *_ in rows]
    near = [r[2] for r in rows]
    lines = [f"{len(rows)} qualifying markets seen ({len({r[8] for r in rows})} categories)",
             f"dollars resting at the NO ask: 10/25/50/75th percentile ${q(at_ask, .10):,.0f} / ${q(at_ask, .25):,.0f} / "
             f"${q(at_ask, .50):,.0f} / ${q(at_ask, .75):,.0f}; within a cent of it: median ${q(near, .50):,.0f}",
             f"a ${rows[0][6]:.0f} order would have filled in full on {sum(1 for r in rows if r[3] and r[3] * r[4] + r[5] >= 0.9 * r[6]) / len(rows):.0%} "
             f"of them, not at all on {sum(1 for r in rows if not r[3]) / len(rows):.0%}"]
    done = [r for r in rows if r[7] in ("yes", "no") and r[3]]
    if done:
        cost = sum(r[3] * r[4] + r[5] for r in done)
        paid = sum(r[4] for r in done if r[7] == "no")
        lines.append(f"settled so far: {len(done)} with a fill, {sum(1 for r in done if r[7] == 'yes')} lost; "
                     f"${cost:,.2f} staked returned ${paid:,.2f} ({paid / cost - 1:+.2%} after fees)")
    else:
        lines.append("none of them has settled yet")
    rest = db.execute("SELECT rest_filled, rest_px, maker_rate, result FROM obs WHERE rest_done = 1").fetchall()
    if rest:
        hit = [r for r in rest if r[0]]
        line = (f"resting NO bid at the best bid, three days: {len(rest)} decided, {len(hit)} filled ({len(hit) / len(rest):.0%}; "
                f"the backtest's model fills about 55% to 60%)")
        done = [r for r in hit if r[3] in ("yes", "no")]
        if done:
            cost = sum(r[1] + (r[2] or 0) * r[1] * (1 - r[1]) for r in done)
            line += f"; of the filled, {len(done)} settled, {sum(1 for r in done if r[3] == 'yes')} lost, {sum(1 for r in done if r[3] == 'no') / cost - 1:+.2%} per dollar"
        lines.append(line)
    else:
        lines.append("resting NO bids: none past its three-day window yet")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--max-new", type=int, default=25)
    ap.add_argument("--min-volume", type=float, default=45000.0,
                    help="contracts traded so far; keep it at the level the backtest was run at")
    ap.add_argument("--categories", default="economics,politics", help="only categories the rule has been tested on")
    ap.add_argument("--pace", type=float, default=2.0, help="seconds between requests")
    args = ap.parse_args()
    db = sqlite3.connect(str(ROOT / "data" / "shadow.db"), timeout=60)
    if args.report:
        print(report(db))
        return 0
    try:
        listing = json.loads((ROOT / "data" / "kalshi_listing.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("no market listing yet (the paper bot writes data/kalshi_listing.json on its first cycle)")
        return 3
    cats = {c.strip().lower() for c in args.categories.split(",") if c.strip()}
    venue = Kalshi(min_interval=args.pace, cache_dir=ROOT / "data")
    proper = {"science and technology": "Science and Technology", "climate and weather": "Climate and Weather"}
    venue._load_series(sorted(proper.get(c, c.title()) for c in cats))
    res = observe(venue, db, listing, cats, time.time(), max_new=args.max_new, min_volume=args.min_volume)
    print(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), f"shadow longshot: looked at {res['looked']}, recorded {res['recorded']}, "
          f"settled {res['settled']}, resting orders decided {res['resting_decided']}; {venue.requests} requests")
    print(report(db))
    return 0


if __name__ == "__main__":
    sys.exit(main())
