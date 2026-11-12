"""Sharadar fundamentals (direct API at api.sharadar.com, Fundamentals plan).

    SHARADAR_API_KEY in .env. Never log or print the key.

load_fundamentals(tickers, ...) returns {feature: date x ticker DataFrame} built with
src.fundamentals from as-reported quarterly rows (dimension ARQ). Raw rows are cached in
<cache_dir>/sharadar_arq.pkl and refreshed incrementally by `lastupdated`.

Ticker mapping: live Norgate symbols equal Sharadar tickers. Norgate's delisted names are
TICKER-YYYYMM; Sharadar keeps the old ticker (adding a digit when it was later reused), so a
delisted name maps to the Sharadar row whose last price date falls within 120 days of that month.
"""
from __future__ import annotations

import io
import os
import re
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

from .fundamentals import ARQ_COLUMNS, daily_panels, quarterly_features

BASE = "https://api.sharadar.com/v1.0"
_DELIST = re.compile(r"^(.*)-(\d{6})$")


def _key() -> str:
    k = os.environ.get("SHARADAR_API_KEY")
    if not k:
        raise RuntimeError("Set SHARADAR_API_KEY in .env")
    return k


RETRY_WAITS = (5, 15, 45, 120)   # seconds between attempts; a reset connection must not kill the daily job


def _get(table: str, **params) -> pd.DataFrame:
    """One page of a table as a DataFrame (CSV). Retries dropped connections, timeouts, 429 and 5xx."""
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            r = requests.get(f"{BASE}/data/{table}", params={**params, "format": "csv"}, headers={"x-api-key": _key()}, timeout=120)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return pd.read_csv(io.StringIO(r.text)) if r.text.strip() else pd.DataFrame()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if attempt == len(RETRY_WAITS) or (status is not None and status < 500 and status != 429):
                raise
            print(f"Sharadar {table}: {type(e).__name__} {status or ''}, retry {attempt + 1} in {RETRY_WAITS[attempt]} s", flush=True)
            time.sleep(RETRY_WAITS[attempt])


def fetch_tickers(cache_dir: str | Path = "data", refresh: bool = False) -> pd.DataFrame:
    """Securities master for the fundamentals table (bulk zip, cached)."""
    p = Path(cache_dir) / "sharadar_tickers.pkl"
    if p.exists() and not refresh:
        return pd.read_pickle(p)
    r = requests.get(f"{BASE}/data/tickers", params={"years": "full"}, headers={"x-api-key": _key()}, allow_redirects=False, timeout=120)
    if r.status_code not in (301, 302, 303, 307):
        raise RuntimeError(f"tickers bulk download failed: HTTP {r.status_code}")
    z = requests.get(r.headers["Location"], timeout=600)
    z.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    t = pd.read_csv(zf.open(zf.namelist()[0]), low_memory=False)
    t = t[t["table"] == "SF1"].copy()
    t["lastpricedate"] = pd.to_datetime(t["lastpricedate"], errors="coerce")
    p.parent.mkdir(parents=True, exist_ok=True)
    t.to_pickle(p)
    return t


def map_tickers(symbols: list[str], tickers: pd.DataFrame) -> dict[str, str]:
    """Norgate symbol -> Sharadar ticker (see module docstring). Unmatched symbols are omitted."""
    f = tickers.copy()
    f["base"] = f["ticker"].str.replace(r"\d+$", "", regex=True)
    by_base = {b: g for b, g in f.groupby("base")}
    out = {}
    for sym in symbols:
        m = _DELIST.match(sym)
        if m:
            base, ym = m.groups()
            g = by_base.get(base)
            if g is None:
                continue
            gap = (g["lastpricedate"] - pd.Timestamp(f"{ym[:4]}-{ym[4:]}-15")).abs().dt.days
            if gap.min() <= 120:
                out[sym] = g.loc[gap.idxmin(), "ticker"]
        else:
            g = by_base.get(sym)
            if g is None:
                continue
            live = g[g["isdelisted"] == "N"]
            out[sym] = (live if len(live) else g.sort_values("lastpricedate")).iloc[-1]["ticker"]
    return out


def fetch_arq(tickers: list[str], start: str = "1997-01-01", since: str | None = None, batch: int = 25) -> pd.DataFrame:   # API limit: 30 tickers per request
    """As-reported quarterly rows for `tickers` (Sharadar symbols). `since` = only rows with
    lastupdated >= since (incremental refresh)."""
    frames = []
    for i in range(0, len(tickers), batch):
        params = {"ticker": ",".join(tickers[i:i + batch]), "dimension": "ARQ", "from": start,
                  "fields": ",".join(ARQ_COLUMNS), "limit": 10000, "sort": "date.asc"}
        if since:
            params["lastupdated.gte"] = since
        skip = 0
        while True:
            page = _get("fundamentals", **params, skip=skip)
            if page.empty:
                break
            frames.append(page)
            if len(page) < 10000:
                break
            skip += len(page)
    if not frames:
        return pd.DataFrame(columns=ARQ_COLUMNS)
    d = pd.concat(frames, ignore_index=True)
    d = d[d["dimension"] == "ARQ"]
    for c in ("calendardate", "date", "reportperiod", "lastupdated"):
        d[c] = pd.to_datetime(d[c])
    return d.drop_duplicates(["ticker", "reportperiod", "date"], keep="last")


def load_fundamentals(symbols: list[str], days: pd.DatetimeIndex, cache_dir: str | Path = "data",
                      refresh: bool = False, start: str = "1997-01-01") -> dict[str, pd.DataFrame]:
    """{feature: date x Norgate-symbol panel} for `symbols` over `days`, from cached + refreshed ARQ rows."""
    cache_dir = Path(cache_dir)
    tk = fetch_tickers(cache_dir)
    mapping = map_tickers(list(symbols), tk)
    wanted = sorted(set(mapping.values()))
    p = cache_dir / "sharadar_arq.pkl"
    rows = pd.read_pickle(p) if p.exists() else pd.DataFrame(columns=ARQ_COLUMNS)
    if len(rows) and not set(ARQ_COLUMNS) <= set(rows.columns):
        # cache written before ARQ_COLUMNS grew: an incremental refresh would never backfill the new columns
        print(f"Sharadar cache lacks {sorted(set(ARQ_COLUMNS) - set(rows.columns))}: refetching all rows")
        rows = pd.DataFrame(columns=ARQ_COLUMNS)
    have = set(rows["ticker"]) if len(rows) else set()
    new = [t for t in wanted if t not in have]
    parts = [rows]
    if new:
        parts.append(fetch_arq(new, start=start))
    if refresh and have:
        last = pd.to_datetime(rows["lastupdated"]).max() if len(rows) else None
        since = (last - pd.Timedelta(days=3)).strftime("%Y-%m-%d") if last is not None else None
        parts.append(fetch_arq(sorted(have & set(wanted)), start=start, since=since))
    rows = pd.concat([x for x in parts if len(x)], ignore_index=True) if any(len(x) for x in parts) else rows
    if len(rows):
        rows = rows.sort_values("lastupdated").drop_duplicates(["ticker", "reportperiod", "date"], keep="last")
        p.parent.mkdir(parents=True, exist_ok=True)
        rows.to_pickle(p)
    by_sh = {t: g for t, g in rows[rows["ticker"].isin(wanted)].groupby("ticker")}
    quarterly = {}
    for sym, sh in mapping.items():
        g = by_sh.get(sh)
        q = quarterly_features(g) if g is not None else None
        if q is not None:
            quarterly[sym] = q
    return daily_panels(quarterly, days)


def fundamentals_from_config(cfg: dict, close: pd.DataFrame, refresh: bool = False) -> dict[str, pd.DataFrame] | None:
    """{feature: panel} for `close`'s names when model.fundamentals is "sharadar", else None."""
    src = (cfg.get("model") or {}).get("fundamentals")
    if not src:
        return None
    if src != "sharadar":
        raise ValueError(f"model.fundamentals must be null or 'sharadar', got {src!r}")
    panels = load_fundamentals(list(close.columns), close.index, refresh=refresh)
    n = int(panels["sue"].iloc[-1].notna().sum()) if panels else 0
    print(f"Fundamentals (sharadar): {len(panels)} features, {n}/{close.shape[1]} names with a current SUE")
    return panels
