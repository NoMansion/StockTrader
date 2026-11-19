"""Family 27: baskets across the outcomes of one event.

If the outcomes of an event exclude each other, at most one YES can win. Buying NO on n of them therefore pays at
least n - 1, whatever happens. When the YES bids of those n outcomes add up to more than 1 (plus fees), the basket
costs less than n - 1: a locked profit, provided the outcomes really are exclusive and every leg fills.

    python research/event_baskets.py --sample liquid --categories Economics,Politics

It takes events whose markets have no numeric strike (a ladder of "above X" questions is not exclusive), forms
the basket on the first day the bids of the legs present add up to the threshold, buys every leg at the next
day's opening quote with the taker fee, and reports what the basket ACTUALLY paid at settlement. One basket per
event.

"No numeric strike" is not the same as "exclusive": "by June?" and "by December?" can both be yes. So the result
is shown three ways: every such event, events Kalshi itself flags as mutually exclusive, and the rest. The flag
is one request per event (`--fetch-flags`, kept in the `events` table of the history database).
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import panel  # noqa: E402


def baskets(df: pd.DataFrame, threshold: float, min_legs: int = 2, max_spread: float = 0.10) -> pd.DataFrame:
    d = df[df["n_ok"] & df["quoted"] & (df["dte"] > 0.25) & (df["spread"] <= max_spread)
           & df["floor_strike"].isna() & df["cap_strike"].isna()]
    if d.empty:
        return pd.DataFrame()
    fee = panel.TAKER * d["mult"] * d["n_bid_op"] * (1 - d["n_bid_op"])
    d = d.assign(cost=(1 - d["n_bid_op"]) + fee, pay=1 - d["y"], sig=d["bid"])
    g = d.groupby(["event", "ts"], sort=False)
    b = g.agg(legs=("ticker", "size"), sig_sum=("sig", "sum"), bid_sum=("n_bid_op", "sum"), cost=("cost", "sum"),
              pay=("pay", "sum"), close=("close_ts", "max"), oos=("oos", "max"), category=("category", "first")).reset_index()
    b = b[(b["legs"] >= min_legs) & (b["sig_sum"] >= threshold)]        # the signal is the bids at the bar's close
    b = b.sort_values("ts").drop_duplicates("event")                    # first day only: one basket per event
    b["ret"] = (b["pay"] - b["cost"]) / b["cost"]
    b["locked"] = (b["legs"] - 1 - b["cost"]) / b["cost"]               # what it must pay if the outcomes are exclusive
    b["hold"] = (b["close"] - b["ts"]) / 86400.0
    return b


def line(b: pd.DataFrame) -> str:
    if b.empty:
        return "none"
    t = b["ret"].mean() / (b["ret"].std(ddof=1) / np.sqrt(len(b))) if len(b) > 2 and b["ret"].std() > 0 else float("nan")
    return (f"{len(b):4d} baskets, {b['legs'].median():.0f} legs (median), mean {b['ret'].mean():+.2%} (t {t:+.1f}), "
            f"worst {b['ret'].min():+.1%}, losing {int((b['ret'] < 0).sum())}, locked at entry {b['locked'].mean():+.2%}, "
            f"held {b['hold'].median():.0f} days")


def flags(db_path) -> dict[str, bool]:
    import sqlite3
    db = sqlite3.connect(str(db_path), timeout=60)
    db.execute("CREATE TABLE IF NOT EXISTS events (event TEXT PRIMARY KEY, mutually_exclusive INTEGER, title TEXT)")
    out = {e: bool(x) for e, x in db.execute("SELECT event, mutually_exclusive FROM events WHERE mutually_exclusive IS NOT NULL")}
    db.close()
    return out


def fetch_flags(db_path, events: list[str], pace: float = 1.5) -> int:
    import sqlite3
    sys.path.insert(0, str(HERE.parent))
    from src.kalshi_http import KalshiError, KalshiHTTP
    known = flags(db_path)
    k, n = KalshiHTTP(min_interval=pace), 0
    db = sqlite3.connect(str(db_path), timeout=60)
    for e in events:
        if e in known:
            continue
        try:
            ev = (k.get(f"/events/{e}", tries=3) or {}).get("event") or {}
        except KalshiError as err:
            if err.status_code == 429:
                break
            continue
        db.execute("INSERT OR REPLACE INTO events VALUES (?,?,?)", (e, None if ev.get("mutually_exclusive") is None
                                                                    else int(bool(ev.get("mutually_exclusive"))), ev.get("title")))
        db.commit()
        n += 1
    db.close()
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(panel.DB))
    ap.add_argument("--categories", default="")
    ap.add_argument("--sample", default="random", choices=["random", "liquid"])
    ap.add_argument("--min-cumvol", type=float, default=None)
    ap.add_argument("--fetch-flags", action="store_true", help="ask Kalshi which of the candidate events are mutually exclusive")
    args = ap.parse_args()
    cats = [c.strip() for c in args.categories.split(",") if c.strip()] or None
    df = panel.load(args.db, cats, sample=args.sample, min_cumvol=args.min_cumvol)
    print(panel.describe(df))
    if df.empty:
        return 1
    if args.fetch_flags:
        cand = baskets(df, 0.90)
        print(f"flags fetched for {fetch_flags(args.db, cand['event'].tolist())} of {len(cand)} candidate events")
    known = flags(args.db)
    for thr in (0.90, 1.00, 1.02, 1.05, 1.10, 1.20):
        b = baskets(df, thr)
        if b.empty:
            print(f"bids add up to {thr:.2f}+: none")
            continue
        ex = b["event"].map(known)
        for label, part in (("all", b), ("exclusive", b[ex == True]), ("not exclusive", b[ex == False])):     # noqa: E712
            print(f"bids add up to {thr:.2f}+, {label:13s}  in sample {line(part[~part['oos']])}")
            print(f"{'':38s}out of sample {line(part[part['oos']])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
