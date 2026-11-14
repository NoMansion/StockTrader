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


RETRY_WAITS = (5, 15, 45, 120, 300, 600)   # seconds between attempts (~18 min in all); then the cached rows are used


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


def map_tickers(symbols: list[str], tickers: pd.DataFrame, first_dates: dict | None = None) -> dict[str, str]:
    """Norgate symbol -> Sharadar ticker (see module docstring). Unmatched symbols are omitted.

    `first_dates` (symbol -> first date with a Norgate price): a Sharadar company whose last price date is more than
    10 days before the Norgate name began is a different, older company that used the ticker before (bug audit
    2026-11-13: FOX was matched to FOX1, the old Fox Entertainment) and is not a candidate. Among live candidates
    the exact ticker wins. Identical to the sweep's fund_common.mapping_v2."""
    f = tickers.copy()
    f["base"] = f["ticker"].str.replace(r"\d+$", "", regex=True)
    by_base = {b: g for b, g in f.groupby("base")}
    first_dates = first_dates or {}
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
            fd = first_dates.get(sym)
            if fd is not None and not pd.isna(fd):
                g = g[g["lastpricedate"].isna() | (g["lastpricedate"] >= pd.Timestamp(fd) - pd.Timedelta(days=10))]
                if g.empty:
                    continue
            live = g[g["isdelisted"] == "N"]
            if len(live):
                exact = live[live["ticker"] == sym]
                out[sym] = (exact if len(exact) else live.sort_values("lastpricedate")).iloc[-1]["ticker"]
            else:
                out[sym] = g.sort_values("lastpricedate").iloc[-1]["ticker"]
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


def _log_error(msg: str, cache_dir: Path) -> None:
    """Loud, persistent error line (data/run_daily_errors.log) that the daily check reads."""
    from datetime import datetime
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print("ERROR: " + msg, flush=True)
    try:
        with open(Path(cache_dir) / "run_daily_errors.log", "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def load_fundamentals(symbols: list[str], days: pd.DatetimeIndex, cache_dir: str | Path = "data",
                      refresh: bool = False, start: str = "1997-01-01", first_dates: dict | None = None,
                      refresh_tickers: bool = False) -> dict[str, pd.DataFrame]:
    """{feature: date x Norgate-symbol panel} for `symbols` over `days`, from cached + refreshed ARQ rows.

    If Sharadar cannot be reached after the retries (outage, rate limit), the cached rows are used and the failure
    is written to data/run_daily_errors.log: one day without today's new filings is far better than skipping the
    day (bug audit 2026-11-13: an outage used to abort the run silently)."""
    cache_dir = Path(cache_dir)
    try:
        tk = fetch_tickers(cache_dir, refresh=refresh_tickers)
    except Exception as e:   # noqa: BLE001 - a stale ticker master is still usable
        if not (cache_dir / "sharadar_tickers.pkl").exists():
            raise
        _log_error(f"Sharadar ticker master refresh failed ({type(e).__name__}: {str(e)[:120]}); using the cached one", cache_dir)
        tk = fetch_tickers(cache_dir)
    mapping = map_tickers(list(symbols), tk, first_dates=first_dates)
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
    try:
        if new:
            parts.append(fetch_arq(new, start=start))
        if refresh and have:
            last = pd.to_datetime(rows["lastupdated"]).max() if len(rows) else None
            since = (last - pd.Timedelta(days=3)).strftime("%Y-%m-%d") if last is not None else None
            parts.append(fetch_arq(sorted(have & set(wanted)), start=start, since=since))
    except Exception as e:   # noqa: BLE001
        if not len(rows):
            raise
        _log_error(f"Sharadar refresh failed ({type(e).__name__}: {str(e)[:120]}); trading on the cached fundamentals "
                   f"(last update {pd.to_datetime(rows['lastupdated']).max().date()})", cache_dir)
        parts = [rows]
    rows = pd.concat([x for x in parts if len(x)], ignore_index=True) if any(len(x) for x in parts) else rows
    if len(rows):
        rows = rows.sort_values("lastupdated").drop_duplicates(["ticker", "reportperiod", "date"], keep="last")
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".pkl.tmp")
        rows.to_pickle(tmp)
        os.replace(tmp, p)
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
    first = close.apply(lambda c: c.first_valid_index())
    # the ticker master is refreshed once a week (new listings, renames); a failure falls back to the cached one
    tk_path = Path("data") / "sharadar_tickers.pkl"
    stale = tk_path.exists() and (pd.Timestamp.now() - pd.Timestamp(tk_path.stat().st_mtime, unit="s")).days >= 7
    panels = load_fundamentals(list(close.columns), close.index, refresh=refresh, first_dates=first.dropna().to_dict(),
                               refresh_tickers=bool(refresh and stale))
    n = int(panels["sue"].iloc[-1].notna().sum()) if panels else 0
    print(f"Fundamentals (sharadar): {len(panels)} features, {n}/{close.shape[1]} names with a current SUE")
    return panels


def filing_marketcaps(symbols: list[str], cache_dir: str | Path = "data", first_dates: dict | None = None) -> dict[str, pd.DataFrame]:
    """Norgate symbol -> its Sharadar filings (`date` = datekey, `marketcap`), from the rows load_fundamentals cached
    (call it first) and the same ticker map. Input to fundamentals.mcap_true (sqrt_mcap sizing)."""
    cache_dir = Path(cache_dir)
    p = cache_dir / "sharadar_arq.pkl"
    if not p.exists():
        return {}
    rows = pd.read_pickle(p)[["ticker", "date", "marketcap"]]
    rows = rows[rows["marketcap"] > 0]
    rows["date"] = pd.to_datetime(rows["date"])
    mapping = map_tickers(list(symbols), fetch_tickers(cache_dir), first_dates=first_dates)
    by_sh = {t: g.sort_values("date").drop_duplicates("date", keep="last")[["date", "marketcap"]]
             for t, g in rows[rows["ticker"].isin(set(mapping.values()))].groupby("ticker")}
    return {sym: by_sh[sh] for sym, sh in mapping.items() if sh in by_sh}
