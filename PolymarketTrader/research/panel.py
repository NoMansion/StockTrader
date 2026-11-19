"""Turn the downloaded Kalshi history (data/kalshi_hist.db) into one table of observations for backtests.

One row per market per daily bar. Everything a rule may look at is known at the END of that bar (`ts`); every price
a rule trades at comes from LATER bars. That separation is the whole point of this file:

  signal columns (known at ts)   bid, ask, mid, spread, days to close, age, volume, momentum, event structure
  execution columns (after ts)   n_bid_op / n_ask_op   quotes at the open of the next bar (taker entries)
                                 f1_*, f3_*            extremes over the next 1 and 3 bars (did a resting order fill?)
  outcome                        result (1 = YES, 0 = NO)

Returns are per dollar staked, after fees, holding to settlement:
  r_yes_tk / r_no_tk     buy at the next bar's opening ask (or 1 - bid for NO), pay the taker fee
  r_yes_mk / r_no_mk     rest a bid at this bar's closing bid (or 1 - ask for NO) for up to 3 bars; counted only if
                         the market traded through the price (ask came down to it, or a trade printed below it)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "kalshi_hist.db"
TAKER, MAKER = 0.07, 0.0175
# In sample: markets closing before this date. Out of sample: from it. Fixed on 2026-11-18 from the calendar alone,
# before any result was seen: Kalshi's volume is so concentrated in 2026 that an earlier date leaves almost
# nothing in sample for most categories, and 2026-04-01 puts roughly half of all events on each side.
SPLIT_TS = int(pd.Timestamp("2026-04-01", tz="UTC").timestamp())


def set_split(date: str) -> None:
    """Move the in-sample / out-of-sample boundary. Choose it from the calendar and the number of events on each
    side only, never from results, and write the choice down before running a sweep."""
    global SPLIT_TS
    SPLIT_TS = int(pd.Timestamp(date, tz="UTC").timestamp())


CENSUS_MARGIN = 1.03       # a market's bars add up to at most 1.023 times its lifetime volume (measured on 9,240 markets)


def census_floor(db, category: str) -> float:
    """Lifetime volume above which EVERY market of the category has been attempted by the download."""
    v = db.execute("SELECT MAX(volume) FROM markets WHERE category=? AND candles_done=0", (category,)).fetchone()[0]
    return float(v or 0.0)


def load(db_path: str | Path = DB, categories: list[str] | None = None, min_bars: int = 2,
         sample: str = "random", min_volume: float = 1.0, min_cumvol: float | None = None) -> pd.DataFrame:
    """Three samples:

    sample="random" (the default) keeps, per category, only the markets drawn in the download's fixed shuffle:
    those whose shuffle key is below the first key not yet attempted. It represents every market that ever traded,
    most of which are tiny.

    sample="liquid" is the census of markets that were ALREADY busy: per category, only the bars at which the
    market had traded at least `min_cumvol` contracts so far (default: the lowest level at which the download is
    complete for that category). Every market that ever reached that level is in the download, so nothing is
    selected on hindsight: a rule sees a market only from the day it qualified. Categories whose download is not
    complete down to `min_cumvol` are left out. Event structure (favourite, ladder) is computed among the
    qualifying markets only.

    sample="all" keeps every downloaded bar, including the early, quiet days of markets that were downloaded
    because they later became big. That selects on lifetime volume, which is hindsight: never judge a rule on it."""
    db = sqlite3.connect(str(db_path), timeout=60)
    cols = {r[1] for r in db.execute("PRAGMA table_info(markets)")}
    where = "WHERE m.candles_done=1"
    args: list = []
    if categories:
        where += f" AND m.category IN ({','.join('?' * len(categories))})"
        args += categories
    floors: dict[str, float] = {}
    if sample == "liquid":
        cats = categories or [r[0] for r in db.execute("SELECT DISTINCT category FROM markets WHERE candles_done=1")]
        for c in cats:
            need = census_floor(db, c) * CENSUS_MARGIN
            if min_cumvol is None:
                floors[c] = max(need, 1.0)
            elif need <= min_cumvol:
                floors[c] = float(min_cumvol)
        if not floors:
            db.close()
            return pd.DataFrame()
        parts = " OR ".join(f"(m.category = ? AND m.volume >= {floors[c] / CENSUS_MARGIN:.4f})" for c in floors)
        where += f" AND ({parts})"
        args += list(floors)
    if sample == "random" and "rnd" in cols:
        fr = dict(db.execute("SELECT category, MIN(rnd) FROM markets WHERE candles_done=0 AND volume>=? GROUP BY category",
                             (min_volume,)).fetchall())
        cats = [r[0] for r in db.execute("SELECT DISTINCT category FROM markets")]
        parts = " OR ".join(f"(m.category = ? AND m.rnd < {int(fr.get(c, 2 ** 32))})" for c in cats)
        where += f" AND ({parts})"
        args += cats
    sched = "m.exp_ts, m.early" if "early" in cols else "NULL AS exp_ts, NULL AS early"
    mk = pd.read_sql_query(
        f"""SELECT m.ticker, m.series, m.event, m.category, m.open_ts, m.close_ts, m.result, m.volume AS tot_vol, {sched},
                   m.strike_type, m.floor_strike, m.cap_strike, s.fee_type, s.fee_multiplier, s.frequency
            FROM markets m LEFT JOIN series s ON s.ticker = m.series {where}""", db, params=args)
    cd = pd.read_sql_query(
        f"""SELECT c.* FROM candles c JOIN markets m ON m.ticker = c.ticker {where} ORDER BY c.ticker, c.ts""", db, params=args)
    # how many markets the exchange listed in each event, downloaded or not: the size of the event as a trader saw it
    listed = pd.read_sql_query("SELECT event, COUNT(*) AS ev_listed FROM markets GROUP BY event", db)
    db.close()
    if cd.empty:
        return cd
    for col in cd.columns:
        if col not in ("ticker", "ts"):
            cd[col] = cd[col].astype("float32")
    mk["y"] = (mk["result"] == "yes").astype("float32")
    mk["mult"] = mk["fee_multiplier"].fillna(1.0).astype("float32")
    mk["maker_fee"] = mk["fee_type"].fillna("").str.contains("maker")
    mk["early"] = pd.to_numeric(mk["early"], errors="coerce")
    mk["exp_ts"] = pd.to_numeric(mk["exp_ts"], errors="coerce")
    df = cd.merge(mk.drop(columns=["result", "fee_type", "fee_multiplier"]), on="ticker", how="inner")
    df = df[df["ts"] <= df["close_ts"] + 86400].copy()

    # ---- signals known at the end of the bar --------------------------------------------------
    df["quoted"] = (df["bid"] > 0) & (df["ask"] < 1) & (df["ask"] > df["bid"])
    df["mid"] = np.where(df["quoted"], (df["bid"] + df["ask"]) / 2, np.nan).astype("float32")
    df["spread"] = np.where(df["quoted"], df["ask"] - df["bid"], np.nan).astype("float32")
    # Days to the end AS KNOWN AT THE TIME. A market that can close early has its close_time rewritten when it does,
    # so its only end date known in advance is the expiration; measuring from the actual close would tell a rule
    # that the event is about to happen. `sched_known` is False where the download has not fetched the schedule
    # yet (those rows fall back to the actual close and must not be trusted for rules that use days to close).
    df["sched_known"] = df["early"].isin([0, 1])
    df["early"] = df["early"] == 1
    end = np.where(df["early"], np.maximum(df["exp_ts"].fillna(df["close_ts"]), df["close_ts"]), df["close_ts"])
    df["end_ts"] = end
    df["dte"] = ((end - df["ts"]) / 86400.0).astype("float32")
    df["dte_real"] = ((df["close_ts"] - df["ts"]) / 86400.0).astype("float32")     # for holding times only
    df["age"] = ((df["ts"] - df["open_ts"]) / 86400.0).astype("float32")
    df["life"] = ((end - df["open_ts"]) / 86400.0).astype("float32")
    df["vol"] = df["vol"].fillna(0.0)
    g = df.groupby("ticker", sort=False)
    df["bar"] = g.cumcount()
    df["nbars"] = g["ts"].transform("size")
    for k in (1, 3, 7):
        df[f"mom{k}"] = (df["mid"] - g["mid"].shift(k)).astype("float32")
    df["vol7"] = g["vol"].transform(lambda s: s.rolling(7, min_periods=1).sum()).astype("float32")
    df["dvol7"] = (df["vol7"] * df["mid"].fillna(df["px"])).astype("float32")           # dollars traded, last 7 bars
    df["cumvol"] = g["vol"].cumsum().astype("float32")

    if floors:                                      # the liquid census: a market exists from the bar it qualified
        df = df[df["cumvol"] >= df["category"].map(floors).astype("float32")].copy()
        if df.empty:
            return df
        df.attrs["floors"] = floors

    # ---- event structure at the same bar --------------------------------------------------------
    ge = df[df["quoted"]].groupby(["event", "ts"], sort=False)["mid"]
    ev = pd.DataFrame({"ev_n": ge.size(), "ev_sum": ge.sum(), "ev_max": ge.max()}).reset_index()
    df = df.merge(ev, on=["event", "ts"], how="left")
    df["ev_fav"] = df["quoted"] & (df["mid"] >= df["ev_max"] - 1e-6)                    # the event's favourite
    # Size of the event: the markets the exchange listed in it. (Until 2026-11-19 this counted only the markets
    # present in the sample, so "an event of one market" could be the one busy market of a thirty-outcome event.)
    df = df.merge(listed, on="event", how="left")
    df["ev_total"] = df["ev_listed"].fillna(1).astype("int32")

    # ---- execution: what happened AFTER the bar ---------------------------------------------------
    g = df.groupby("ticker", sort=False)
    df["n_bid_op"], df["n_ask_op"] = g["bid_op"].shift(-1), g["ask_op"].shift(-1)
    df["n_ok"] = (df["n_bid_op"] > 0) & (df["n_ask_op"] < 1) & (df["n_ask_op"] > df["n_bid_op"])
    for k in (1, 3):
        lo = pd.concat([g["ask_lo"].shift(-i) for i in range(1, k + 1)], axis=1).min(axis=1)
        plo = pd.concat([g["px_lo"].shift(-i) for i in range(1, k + 1)], axis=1).min(axis=1)
        hi = pd.concat([g["bid_hi"].shift(-i) for i in range(1, k + 1)], axis=1).max(axis=1)
        phi = pd.concat([g["px_hi"].shift(-i) for i in range(1, k + 1)], axis=1).max(axis=1)
        # a resting YES bid at `bid` fills if the ask came down to it or a trade printed below it
        df[f"f{k}_yes"] = df["quoted"] & ((lo <= df["bid"] + 1e-6) | (plo < df["bid"] - 1e-6))
        # a resting NO bid at 1 - ask fills if the YES bid rose to the ask or a trade printed above it
        df[f"f{k}_no"] = df["quoted"] & ((hi >= df["ask"] - 1e-6) | (phi > df["ask"] + 1e-6))

    # ---- returns per dollar staked, after fees, held to settlement -----------------------------
    y = df["y"]

    def fee(p, rate):
        return rate * df["mult"] * p * (1 - p)

    c = df["n_ask_op"] + fee(df["n_ask_op"], TAKER)
    df["r_yes_tk"] = np.where(df["n_ok"], (y - c) / c, np.nan).astype("float32")
    c = (1 - df["n_bid_op"]) + fee(df["n_bid_op"], TAKER)
    df["r_no_tk"] = np.where(df["n_ok"], ((1 - y) - c) / c, np.nan).astype("float32")
    mrate = np.where(df["maker_fee"], MAKER, 0.0)
    c = df["bid"] + mrate * df["mult"] * df["bid"] * (1 - df["bid"])
    df["r_yes_mk"] = np.where(df["f3_yes"], (y - c) / c, np.nan).astype("float32")
    c = (1 - df["ask"]) + mrate * df["mult"] * df["ask"] * (1 - df["ask"])
    df["r_no_mk"] = np.where(df["f3_no"], ((1 - y) - c) / c, np.nan).astype("float32")
    df["oos"] = df["close_ts"] >= SPLIT_TS
    df = df[df["nbars"] >= min_bars].reset_index(drop=True)
    return ladder(df)


def ladder(df: pd.DataFrame) -> pd.DataFrame:
    """Threshold ladders: markets of one event that ask "above X?" for a rising X. The next rung up can never be
    MORE likely than this one. For each row, the quotes of the next rung up at the same bar, and the return of the
    pair trade that locks the ordering in (buy YES here, buy NO one rung up; it pays at least 1 whatever happens)."""
    for col in ("up_bid", "up_ask", "up_mid", "dn_mid", "r_pair_tk", "pair_cost"):
        df[col] = np.float32(np.nan)
    lad = df[(df["strike_type"] == "greater") & df["floor_strike"].notna()].sort_values(["event", "ts", "floor_strike"])
    if lad.empty:
        return df
    g = lad.groupby(["event", "ts"], sort=False)
    up = pd.DataFrame({"up_bid": g["bid"].shift(-1), "up_ask": g["ask"].shift(-1), "up_mid": g["mid"].shift(-1),
                       "up_n_bid": g["n_bid_op"].shift(-1), "up_n_ok": g["n_ok"].shift(-1), "up_y": g["y"].shift(-1),
                       "up_quoted": g["quoted"].shift(-1)}, index=lad.index)
    ok = lad["n_ok"] & (up["up_n_ok"] == True) & (up["up_quoted"] == True)        # noqa: E712
    fee = TAKER * lad["mult"] * (lad["n_ask_op"] * (1 - lad["n_ask_op"]) + up["up_n_bid"] * (1 - up["up_n_bid"]))
    cost = lad["n_ask_op"] + (1 - up["up_n_bid"]) + fee
    pay = lad["y"] + (1 - up["up_y"])
    df.loc[lad.index, "up_bid"], df.loc[lad.index, "up_ask"] = up["up_bid"].astype("float32"), up["up_ask"].astype("float32")
    df.loc[lad.index, "up_mid"] = up["up_mid"].astype("float32")
    df.loc[lad.index, "dn_mid"] = g["mid"].shift(1).astype("float32")              # the next rung DOWN: never less likely
    df.loc[lad.index, "pair_cost"] = np.where(ok, cost, np.nan).astype("float32")
    df.loc[lad.index, "r_pair_tk"] = np.where(ok, (pay - cost) / cost, np.nan).astype("float32")
    return df


def describe(df: pd.DataFrame) -> str:
    if df.empty:
        return "no observations yet"
    m = df.drop_duplicates("ticker")
    lines = [f"{len(m):,} markets, {m['event'].nunique():,} events, {len(df):,} daily bars; "
             f"closes {pd.to_datetime(m['close_ts'].min(), unit='s').date()} to {pd.to_datetime(m['close_ts'].max(), unit='s').date()}; "
             f"{int(m['oos'].sum()):,} markets out of sample (closing from {pd.to_datetime(SPLIT_TS, unit='s').date()})"]
    if df.attrs.get("floors"):
        lines.append("  liquid census: bars from the day a market had traded at least "
                     + ", ".join(f"{v:,.0f} contracts ({c})" for c, v in df.attrs["floors"].items()))
    by = m.groupby("category").agg(markets=("ticker", "size"), events=("event", "nunique"), yes=("y", "mean"), oos=("oos", "sum"),
                                   early=("early", "mean"), known=("sched_known", "mean"))
    for cat, r in by.iterrows():
        lines.append(f"  {cat:24s} {int(r.markets):7,} markets {int(r.events):6,} events  resolved yes {r.yes:5.1%}  out of sample {int(r.oos):6,}"
                     f"  can close early {r.early:4.0%}" + ("" if r.known > 0.999 else f"  SCHEDULE MISSING FOR {1 - r.known:.0%}"))
    return "\n".join(lines)


if __name__ == "__main__":
    d = load()
    print(describe(d))
