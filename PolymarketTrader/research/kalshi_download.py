"""Build a local history of settled Kalshi markets for strategy research (data/kalshi_hist.db).

Public endpoints only, paced, resumable: stop it at any point and run it again. Three phases, each skipped once done:

  series   every series (a recurring question such as "CPI year-over-year") in the chosen categories
  markets  every settled market of those series in the archive (/historical/markets, back to 2022)
  candles  daily bid / ask / trade bars for each market from open to close, in a RANDOM order within each
           category (a fixed shuffle: the checksum of the ticker). Random on purpose: taking the biggest markets
           first, as the first version did, selects on lifetime volume, which is only known afterwards and is
           larger for markets where something surprising happened. Backtests use only the random sample.
  recent   markets settled since the archive cutoff (/markets?status=settled) and their bars; last and slowest,
           because that endpoint throttles hard

The data stays on this machine (data/ is not committed): Kalshi's terms do not allow redistributing it.

    python research/kalshi_download.py                       all phases, default categories
    python research/kalshi_download.py --phase candles --min-volume 200 --max-markets 50000
"""
import argparse
import sqlite3
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.kalshi_http import KalshiError, KalshiHTTP  # noqa: E402

# In the order they are downloaded: the categories the paper bot trades first, the giant ones last.
CATEGORIES = ["Economics", "Politics", "Companies", "Commodities", "Science and Technology", "Elections", "Health",
              "World", "Financials", "Mentions", "Entertainment", "Crypto", "Social", "Climate and Weather", "Sports"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (ticker TEXT PRIMARY KEY, category TEXT, title TEXT, fee_type TEXT, fee_multiplier REAL,
    frequency TEXT, tags TEXT, markets_done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS markets (ticker TEXT PRIMARY KEY, series TEXT, event TEXT, category TEXT, title TEXT, sub TEXT,
    open_ts INTEGER, close_ts INTEGER, result TEXT, settle REAL, volume REAL, open_interest REAL, last_price REAL,
    strike_type TEXT, floor_strike REAL, cap_strike REAL, src TEXT, candles_done INTEGER DEFAULT 0, rnd INTEGER);
CREATE INDEX IF NOT EXISTS markets_series ON markets (series);
CREATE INDEX IF NOT EXISTS markets_todo ON markets (candles_done, category, volume);
CREATE TABLE IF NOT EXISTS candles (ticker TEXT, ts INTEGER, bid REAL, ask REAL, bid_hi REAL, bid_lo REAL, ask_hi REAL,
    ask_lo REAL, px REAL, px_hi REAL, px_lo REAL, vol REAL, oi REAL, bid_op REAL, ask_op REAL, px_mean REAL,
    PRIMARY KEY (ticker, ts)) WITHOUT ROWID;
"""


def ts(s):
    try:
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def first(d, *keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def phase_series(db, k, categories):
    for cat in categories:
        if db.execute("SELECT 1 FROM series WHERE category=? LIMIT 1", (cat,)).fetchone():
            continue
        rows = k.get("/series", category=cat).get("series") or []
        db.executemany("INSERT OR IGNORE INTO series (ticker, category, title, fee_type, fee_multiplier, frequency, tags) VALUES (?,?,?,?,?,?,?)",
                       [(s["ticker"], cat, s.get("title"), s.get("fee_type"), num(s.get("fee_multiplier")), s.get("frequency"),
                         ",".join(s.get("tags") or [])) for s in rows])
        db.commit()
        log(f"series: {cat}: {len(rows)}")


def shuffle_key(ticker: str) -> int:
    """A fixed pseudo-random number per market: its position in the download order and in the sample."""
    return zlib.crc32(ticker.encode("utf-8"))


def frontier(db, category: str, min_volume: float) -> int:
    """Markets of the category with a shuffle key below this number have all been attempted: they ARE the random
    sample. (2**32 when the whole category is done.)"""
    row = db.execute("SELECT MIN(rnd) FROM markets WHERE category=? AND candles_done=0 AND volume>=?", (category, min_volume)).fetchone()
    return int(row[0]) if row and row[0] is not None else 2 ** 32


def market_row(m, series, category, src):
    return (m["ticker"], series, m.get("event_ticker"), category, m.get("title"), first(m, "yes_sub_title", "subtitle"),
            ts(m.get("open_time")), ts(m.get("close_time")), m.get("result"),
            num(first(m, "settlement_value_dollars", "settlement_value")), num(first(m, "volume_fp", "volume")),
            num(first(m, "open_interest_fp", "open_interest")), num(first(m, "last_price_dollars", "last_price")),
            m.get("strike_type"), num(m.get("floor_strike")), num(m.get("cap_strike")), src, shuffle_key(m["ticker"]))


def phase_markets(db, k, categories, max_per_series, which):
    """which = "hist" (the archive) or "recent" (settled since the archive cutoff). markets_done is a bit mask:
    1 = archive listed, 2 = recent listed. The live endpoint behind "recent" throttles hard, so it is paced slower
    and a series that cannot be read now is simply left for the next run."""
    bit = 1 if which == "hist" else 2
    path, extra = ("/historical/markets", {}) if which == "hist" else ("/markets", {"status": "settled"})
    todo = db.execute(f"SELECT ticker, category FROM series WHERE (markets_done & ?) = 0 AND category IN "
                      f"({','.join('?' * len(categories))}) ORDER BY category, ticker", [bit] + categories).fetchall()
    log(f"markets[{which}]: {len(todo)} series to list")
    failures = 0
    for i, (series, cat) in enumerate(todo):
        batch, ok = [], True
        try:
            for m in k.pages(path, "markets", tries=3, series_ticker=series, **extra):
                if m.get("result") not in ("yes", "no"):              # scalar or voided markets are left out
                    continue
                batch.append(market_row(m, series, cat, which))
                if len(batch) >= max_per_series:
                    break
        except KalshiError as e:
            ok = e.status_code == 404
            if not ok:
                failures += 1
                log(f"markets[{which}]: {series}: {e}")
                if failures >= 5:
                    log(f"markets[{which}]: the endpoint keeps refusing: stopping this phase, the rest waits for the next run")
                    db.commit()
                    return
                time.sleep(60)
        db.executemany("INSERT OR IGNORE INTO markets (ticker, series, event, category, title, sub, open_ts, close_ts, result, "
                       "settle, volume, open_interest, last_price, strike_type, floor_strike, cap_strike, src, rnd) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        if ok:
            failures = 0
            db.execute("UPDATE series SET markets_done = markets_done | ? WHERE ticker=?", (bit, series))
        db.commit()
        if i % 200 == 0:
            total = db.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
            log(f"markets[{which}]: {i}/{len(todo)} series, {total} markets so far ({cat} {series}: {len(batch)}); "
                f"{k.requests} requests, {k.rate_limited} rate limits, interval {k.min_interval:.2f}s")


def candle_rows(ticker, cs):
    out = []
    for c in cs:
        def g(group, field):
            d = c.get(group) or {}
            return num(first(d, field + "_dollars", field))
        out.append((ticker, c.get("end_period_ts"), g("yes_bid", "close"), g("yes_ask", "close"), g("yes_bid", "high"),
                    g("yes_bid", "low"), g("yes_ask", "high"), g("yes_ask", "low"), g("price", "close"), g("price", "high"),
                    g("price", "low"), num(first(c, "volume_fp", "volume")), num(first(c, "open_interest_fp", "open_interest")),
                    g("yes_bid", "open"), g("yes_ask", "open"), g("price", "mean")))
    return [r for r in out if r[1]]


def phase_candles(db, k, categories, min_volume, max_markets, max_days):
    done = 0
    cats = [c for c in categories if db.execute("SELECT 1 FROM markets WHERE category=? AND candles_done=0 AND volume>=? LIMIT 1",
                                                (c, min_volume)).fetchone()]
    log(f"candles: categories with work: {cats}")
    while cats and done < max_markets:
        for cat in list(cats):                      # round-robin across categories, biggest markets first
            rows = db.execute("SELECT ticker, series, open_ts, close_ts, src FROM markets WHERE category=? AND candles_done=0 "
                              "AND volume>=? ORDER BY rnd LIMIT 40", (cat, min_volume)).fetchall()
            if not rows:
                cats.remove(cat)
                continue
            for ticker, series, o, cl, src in rows:
                status = 1
                if not o or not cl or cl <= o:
                    status = 3
                else:
                    start = max(o, cl - max_days * 86400)
                    path = (f"/historical/markets/{ticker}/candlesticks" if src == "hist"
                            else f"/series/{series}/markets/{ticker}/candlesticks")
                    try:
                        cs = k.get(path, start_ts=start, end_ts=cl + 86400, period_interval=1440).get("candlesticks") or []
                        db.executemany("INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", candle_rows(ticker, cs))
                        if not cs:
                            status = 2              # no bars: never quoted
                    except KalshiError as e:
                        status = 4 if e.status_code == 404 else 0
                        if status == 0:
                            log(f"candles: {ticker}: {e}")
                    except Exception as e:          # network trouble: leave it for the next run
                        status = 0
                        log(f"candles: {ticker}: {type(e).__name__}")
                        time.sleep(10)
                if status:
                    db.execute("UPDATE markets SET candles_done=? WHERE ticker=?", (status, ticker))
                done += 1
            db.commit()
            if done % 2000 < 40:
                n = db.execute("SELECT COUNT(*) FROM markets WHERE candles_done=1").fetchone()[0]
                log(f"candles: {n} markets with bars; {k.requests} requests, {k.rate_limited} rate limits, interval {k.min_interval:.2f}s")
    log(f"candles: finished this pass ({done} markets)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "kalshi_hist.db"))
    ap.add_argument("--phase", default="all", choices=["all", "series", "markets", "recent", "candles"])
    ap.add_argument("--categories", default=",".join(c for c in CATEGORIES if c != "Sports"))
    ap.add_argument("--min-volume", type=float, default=1.0,
                    help="lifetime contracts traded; keep it at 1 (any trade at all): a higher bar selects on hindsight")
    ap.add_argument("--max-markets", type=int, default=10 ** 9)
    ap.add_argument("--first-pass", type=int, default=4000, help="markets per category to get bars for in the first pass")
    ap.add_argument("--max-per-series", type=int, default=200000)
    ap.add_argument("--max-days", type=int, default=400)
    ap.add_argument("--interval", type=float, default=0.2, help="seconds between requests")
    args = ap.parse_args()
    cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.db, timeout=60)
    db.executescript(SCHEMA)
    if "rnd" not in {r[1] for r in db.execute("PRAGMA table_info(markets)")}:      # databases from before the shuffle
        db.execute("ALTER TABLE markets ADD COLUMN rnd INTEGER")
    todo = db.execute("SELECT ticker FROM markets WHERE rnd IS NULL").fetchall()
    if todo:
        db.executemany("UPDATE markets SET rnd=? WHERE ticker=?", [(shuffle_key(t[0]), t[0]) for t in todo])
        db.commit()
    db.execute("CREATE INDEX IF NOT EXISTS markets_rnd ON markets (category, candles_done, rnd)")
    db.execute("PRAGMA journal_mode=WAL")
    k = KalshiHTTP(min_interval=args.interval)
    if args.phase in ("all", "series"):
        phase_series(db, k, cats)
    if args.phase == "all":
        # First pass, one category at a time: list its markets, then fetch bars for its biggest ones. Analysis can
        # start on the first categories while the later ones are still downloading.
        for cat in cats:
            phase_markets(db, k, [cat], args.max_per_series, "hist")
            have = db.execute("SELECT COUNT(*) FROM markets WHERE category=? AND volume>=? AND rnd<?",
                              (cat, args.min_volume, frontier(db, cat, args.min_volume))).fetchone()[0]
            if have < args.first_pass:              # a restart does not repeat a category's first pass
                phase_candles(db, k, [cat], args.min_volume, args.first_pass - have, args.max_days)
    if args.phase in ("all", "markets"):                # also picks up any series a throttled pass left behind
        phase_markets(db, k, cats, args.max_per_series, "hist")
    if args.phase in ("all", "candles"):
        phase_candles(db, k, cats, args.min_volume, args.max_markets, args.max_days)
    if args.phase in ("all", "recent"):                 # last: the live endpoint is the touchy one
        k.min_interval = max(k.min_interval, 0.6)
        phase_markets(db, k, cats, args.max_per_series, "recent")
        phase_candles(db, k, cats, args.min_volume, args.max_markets, args.max_days)
    db.close()


if __name__ == "__main__":
    main()
