"""Norgate Data provider (Windows; needs Norgate Data Updater running and a
Platinum/Diamond US Stocks subscription for delisted + index history).

    pip install norgatedata

Two things this module adds over the other providers:

1. `fetch_bars(...)` — daily bars for a list of symbols, with BOTH the
   total-return adjusted close (for features/labels) and the unadjusted close
   (for order sizing), plus `assetid` as a permanent security id.
2. `point_in_time_universe(...)` — the set of symbols that were members of an
   index (e.g. "S&P 500", "Russell 1000") on each date, including names that
   have since delisted. This is the thing cheap data cannot give you.

Not unit-tested here (package is Windows-only); the function signatures follow
the norgatedata docs. Run `python scripts/norgate_smoke.py` on your PC first.
"""
from __future__ import annotations

import pandas as pd

from .data import COLS

# Norgate database names. "US Equities Delisted" is the survivorship-bias fix.
DB_ACTIVE = "US Equities"
DB_DELISTED = "US Equities Delisted"


def _nd():
    import norgatedata  # Windows-only; imported lazily so the rest of the project runs anywhere
    return norgatedata


def list_symbols(include_delisted: bool = True, common_stock_only: bool = True) -> list[str]:
    """All US symbols (active + delisted). With `common_stock_only`, keeps only
    operating/holding companies: drops ETFs/ETNs, closed-end & investment
    companies, SPAC shells, warrants, rights, preferreds and debt so a
    liquidity-ranked universe isn't polluted by them.

    Norgate's taxonomy (checked against NDU, Nov 2026): base_type is
    "Stock Market" for everything; subtype1 is "Equity" / "Exchange Traded
    Product" / "Derivative" / "Hybrid" / "Debt"; subtype2 distinguishes
    "Operating/Holding Company" from "Special Purpose Company" (SPAC),
    "Investment Company", "Warrant (Company Issued)", "Preferred", etc."""
    nd = _nd()
    syms = list(nd.database_symbols(DB_ACTIVE))
    if include_delisted:
        syms += list(nd.database_symbols(DB_DELISTED))
    syms = sorted(set(syms))
    if not common_stock_only:
        return syms
    keep = []
    for s in syms:
        try:
            if nd.subtype1(s) != "Equity":
                continue
            if nd.subtype2(s) != "Operating/Holding Company":
                continue
            keep.append(s)
        except Exception:
            keep.append(s)   # metadata call failed: keep and let liquidity decide
    return keep


def major_exchange_membership(symbols: list[str], start: str) -> pd.DataFrame:
    """date x ticker booleans: True while listed on a major exchange (NYSE/NASDAQ/AMEX),
    False once a name is relegated to OTC. Used to make the liquidity universe
    point-in-time clean (formerly-listed OTC names are in the Platinum database)."""
    nd = _nd()
    cols = {}
    for s in symbols:
        try:
            ts = nd.major_exchange_listed_timeseries(s, timeseriesformat="pandas-dataframe")
        except Exception:
            continue
        if ts is None or len(ts) == 0:
            continue
        ts.index = pd.to_datetime(ts.index).tz_localize(None).normalize()
        ts = ts[ts.index >= pd.Timestamp(start)]
        if len(ts):
            cols[s] = ts.iloc[:, -1].astype(bool)
    return pd.DataFrame(cols).sort_index() if cols else pd.DataFrame()


def fetch_bars(symbols: list[str], start: str, end: str | None = None) -> pd.DataFrame:
    """Long table in the project's standard shape, plus `assetid`."""
    nd = _nd()
    frames = []
    for s in symbols:
        try:
            adj = nd.price_timeseries(
                s, stock_price_adjustment_setting=nd.StockPriceAdjustmentType.TOTALRETURN,
                padding_setting=nd.PaddingType.NONE, start_date=start, end_date=end,
                timeseriesformat="pandas-dataframe",
            )
            raw = nd.price_timeseries(
                s, stock_price_adjustment_setting=nd.StockPriceAdjustmentType.NONE,
                padding_setting=nd.PaddingType.NONE, start_date=start, end_date=end,
                timeseriesformat="pandas-dataframe",
            )
        except Exception:
            continue
        if adj is None or len(adj) == 0:
            continue
        adj = adj.rename(columns=str.lower)
        raw = raw.rename(columns=str.lower)
        df = pd.DataFrame({
            "date": pd.to_datetime(adj.index).tz_localize(None).normalize(),
            "ticker": s,
            "open": raw["open"].values, "high": raw["high"].values, "low": raw["low"].values,
            "close": raw["close"].values, "volume": raw["volume"].values,
            "adj_close": adj["close"].values,
        })
        df["assetid"] = nd.assetid(s)
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=COLS + ["assetid"])
    return pd.concat(frames, ignore_index=True)


def security_master(symbols: list[str]) -> pd.DataFrame:
    """Per-symbol metadata incl. delist date (last_quoted_date is None if active)."""
    nd = _nd()
    rows = []
    for s in symbols:
        try:
            rows.append({
                "ticker": s, "assetid": nd.assetid(s), "name": nd.security_name(s),
                "exchange": nd.exchange_name(s),
                "first_date": pd.Timestamp(nd.first_quoted_date(s, datetimeformat="date")),
                "last_date": pd.Timestamp(nd.last_quoted_date(s, datetimeformat="date")) if nd.last_quoted_date(s, datetimeformat="date") else pd.NaT,
                "sector": nd.classification_at_level(s, "GICS", "Name", 1),
            })
        except Exception:
            continue
    return pd.DataFrame(rows)


def point_in_time_universe(symbols: list[str], index_name: str, start: str) -> pd.DataFrame:
    """date x ticker boolean matrix: True where `ticker` was in `index_name` on `date`.

    Platinum/Diamond only. Typical index_name values: "S&P 500", "Russell 1000",
    "Russell 3000", "NASDAQ 100". Pass symbols from list_symbols(include_delisted=True).
    """
    nd = _nd()
    cols = {}
    for s in symbols:
        try:
            ts = nd.index_constituent_timeseries(
                s, index_name, padding_setting=nd.PaddingType.NONE, start_date=start,
                timeseriesformat="pandas-dataframe",
            )
        except Exception:
            continue
        if ts is None or len(ts) == 0:
            continue
        ts = ts.rename(columns=str.lower)
        col = [c for c in ts.columns if "index constituent" in c or c == "index constituent"]
        if not col:
            continue
        member = ts[col[0]].astype(bool)
        member.index = pd.to_datetime(ts.index).tz_localize(None).normalize()
        if member.any():
            cols[s] = member
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).fillna(False).sort_index()
