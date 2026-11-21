"""Daily bar loading with a pluggable provider and a Parquet cache.

Providers return a long DataFrame: date, ticker, open, high, low, close,
volume, adj_close. `adj_close` is split+dividend adjusted (total return).

    bars = load_bars(tickers, start, provider="yfinance")
    wide_close = to_wide(bars, "adj_close")
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

COLS = ["date", "ticker", "open", "high", "low", "close", "volume", "adj_close"]


# ---------------------------------------------------------------- providers
def _fetch_yfinance(tickers: list[str], start: str, end: str | None) -> pd.DataFrame:
    """Free, fine for development. Not survivorship-bias free (see DATA_PLAN.md)."""
    import yfinance as yf  # optional dependency

    raw = yf.download(
        tickers, start=start, end=end, auto_adjust=False, actions=False,
        group_by="ticker", progress=False, threads=True,
    )
    frames = []
    for t in tickers:
        try:
            df = raw[t].copy() if len(tickers) > 1 else raw.copy()
        except KeyError:
            continue
        df = df.rename(columns=str.lower).rename(columns={"adj close": "adj_close"})
        df["ticker"] = t
        df.index.name = "date"
        frames.append(df.reset_index())
    if not frames:
        return pd.DataFrame(columns=COLS)
    out = pd.concat(frames, ignore_index=True)
    return out[COLS]


def _fetch_tiingo(tickers: list[str], start: str, end: str | None) -> pd.DataFrame:
    """Tiingo EOD endpoint. Needs TIINGO_API_KEY. ~$10/mo Power tier is plenty."""
    import requests  # stdlib-adjacent; present in most envs

    key = os.environ.get("TIINGO_API_KEY")
    if not key:
        raise RuntimeError("Set TIINGO_API_KEY in .env")
    frames = []
    for t in tickers:
        r = requests.get(
            f"https://api.tiingo.com/tiingo/daily/{t}/prices",
            params={"startDate": start, "endDate": end, "format": "json", "token": key},
            timeout=30,
        )
        if r.status_code != 200:
            continue
        df = pd.DataFrame(r.json())
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        df = df.rename(columns={"adjClose": "adj_close"})
        df["ticker"] = t
        frames.append(df[COLS])
    if not frames:
        return pd.DataFrame(columns=COLS)
    return pd.concat(frames, ignore_index=True)


def _fetch_norgate(tickers: list[str], start: str, end: str | None) -> pd.DataFrame:
    """Norgate Data (Windows, NDU running). Survivorship-bias free with Platinum+."""
    from .providers_norgate import fetch_bars
    return fetch_bars(tickers, start, end)[COLS]


PROVIDERS = {"yfinance": _fetch_yfinance, "tiingo": _fetch_tiingo, "norgate": _fetch_norgate}


# ---------------------------------------------------------------- public API
def load_bars(
    tickers: list[str],
    start: str,
    end: str | None = None,
    provider: str = "yfinance",
    cache_dir: str | Path = "data",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load daily bars, using a Parquet cache keyed on provider + start date."""
    bars = _load_raw_bars(tickers, start, end, provider, cache_dir, refresh)
    # Memory (2026-11-21): filter without copying when nothing is dropped, and let clean_bars work on this frame
    # instead of copying it again.
    keep = bars["ticker"].isin(tickers)
    if not keep.all():
        bars = bars[keep]
    del keep
    bars = bars.assign(date=pd.to_datetime(bars["date"]))
    return clean_bars(bars, copy=False)


def load_wide(
    tickers: list[str],
    start: str,
    fields: list[str],
    end: str | None = None,
    provider: str = "yfinance",
    cache_dir: str | Path = "data",
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """{field: date x ticker matrix} of clean bars: the same as to_wide_many(load_bars(...), fields), without ever
    holding a cleaned copy of the long frame. The live job loads ~12k tickers x 16 years here (24M rows); the
    load_bars route peaked at ~5.5 GB, mostly from several full copies of that frame alive at once."""
    raw = _load_raw_bars(tickers, start, end, provider, cache_dir, refresh)
    return clean_wide(raw, fields, tickers=tickers)


def write_parquet_chunked(df: pd.DataFrame, path: Path, rows_per_chunk: int = 2_000_000) -> None:
    """df.to_parquet(path, index=False), converting to Arrow a slice at a time: to_parquet makes a full Arrow copy
    of the frame first (~2 GB for the live job's bars). Written to a temporary file and moved into place, so a
    crash never leaves a half-written cache."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    tmp = path.with_suffix(path.suffix + ".tmp")
    writer = None
    try:
        for i in range(0, max(len(df), 1), rows_per_chunk):
            t = pa.Table.from_pandas(df.iloc[i:i + rows_per_chunk], preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(tmp, t.schema)
            writer.write_table(t)
            del t
    finally:
        if writer is not None:
            writer.close()
    os.replace(tmp, path)


def _load_raw_bars(tickers, start, end, provider, cache_dir, refresh) -> pd.DataFrame:
    """The provider's long frame through the Parquet cache, unfiltered and uncleaned."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"bars_{provider}_{start}.parquet"

    # Sidecar: every ticker ever requested from this cache. Tickers that returned
    # no bars (e.g. names delisted before `start`) are recorded too, so they are
    # not re-fetched on every load.
    attempted_file = cache.with_suffix(".attempted.json")

    def _attempted() -> set[str]:
        if attempted_file.exists():
            return set(json.loads(attempted_file.read_text()))
        return set()

    def _remember(ts: list[str]) -> None:
        attempted_file.write_text(json.dumps(sorted(_attempted() | set(ts))))

    if cache.exists() and not refresh:
        bars = pd.read_parquet(cache)
        have = set(bars["ticker"].unique()) | _attempted()
        missing = [t for t in tickers if t not in have]
        if missing:
            new = PROVIDERS[provider](missing, start, end)
            if len(new):
                bars = pd.concat([bars, new], ignore_index=True)
                write_parquet_chunked(bars, cache)
            _remember(missing)
    else:
        bars = PROVIDERS[provider](tickers, start, end)
        write_parquet_chunked(bars, cache)
        attempted_file.write_text(json.dumps(sorted(set(tickers))))
    return bars


def _clean_mask(bars: pd.DataFrame) -> np.ndarray:
    """Rows clean_bars keeps (before de-duplication), as a boolean array:
    - close / adj_close present
    - Norgate stores 0.000001 as a "no trade" placeholder on some OTC names; a bar at that price is not a price,
      and the return off it is +1e8%
    - bad prints: high < low or close outside [low, high]"""
    num = lambda c: pd.to_numeric(bars[c], errors="coerce").to_numpy(dtype="float64")
    close, adj, high, low = num("close"), num("adj_close"), num("high"), num("low")
    with np.errstate(invalid="ignore"):
        return (~np.isnan(close) & ~np.isnan(adj) & (close > 1e-4) & (adj > 0)
                & (high >= low) & (close <= high * 1.0001) & (close >= low * 0.9999))


def clean_wide(bars: pd.DataFrame, fields: list[str], tickers: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """{field: date x ticker matrix} equal to to_wide_many(clean_bars(bars restricted to `tickers`), fields), built
    by position from the raw frame: no cleaned or sorted copy of the long frame is ever made. Of duplicate
    (date, ticker) rows the last one wins, as in clean_bars."""
    ok = _clean_mask(bars)
    if tickers is not None:
        ok &= bars["ticker"].isin(tickers).to_numpy()
    pos = np.flatnonzero(ok)
    del ok
    d_codes, dates = pd.factorize(pd.to_datetime(bars["date"].take(pos)), sort=True)
    t_codes, names = pd.factorize(bars["ticker"].take(pos), sort=True)
    if (d_codes < 0).any() or (t_codes < 0).any():
        raise ValueError("bars have a missing date or ticker")
    nd, nt = len(dates), len(names)
    # last row per (date, ticker): a stable sort on the cell key keeps file order within a cell
    key = d_codes.astype("int64") * nt + t_codes
    del d_codes, t_codes
    order = np.argsort(key, kind="stable")
    key = key[order]
    last = np.ones(len(key), dtype=bool)
    last[:-1] = key[1:] != key[:-1]
    order, key = order[last], key[last]
    del last
    rows = pos[order]
    del pos, order
    index = (dates if isinstance(dates, pd.DatetimeIndex) else pd.DatetimeIndex(dates)).rename("date")
    columns = pd.Index(names, name="ticker")
    out = {}
    for f in fields:
        vals = pd.to_numeric(bars[f], errors="coerce").to_numpy(dtype="float64")[rows]
        arr = np.full(nd * nt, np.nan)
        arr[key] = vals
        del vals
        out[f] = pd.DataFrame(arr.reshape(nd, nt), index=index, columns=columns, copy=False)
    return out


def clean_bars(bars: pd.DataFrame, copy: bool = True) -> pd.DataFrame:
    """Minimal hygiene. The full pipeline is specified in DATA_PLAN.md.

    copy=False: the caller hands over `bars` and does not use it again (saves one full copy of a large frame)."""
    b = bars.copy() if copy else bars
    for c in ["open", "high", "low", "close", "volume", "adj_close"]:
        b[c] = pd.to_numeric(b[c], errors="coerce").astype("float64")   # never let object dtype through
    close, adj, high, low = b["close"], b["adj_close"], b["high"], b["low"]
    # one combined filter (one copy) instead of three successive ones; the same rows survive:
    # - close / adj_close present
    # - Norgate stores 0.000001 as a "no trade" placeholder on some OTC names; a bar at that price is not a price,
    #   and the return off it is +1e8%
    # - bad prints: high < low or close outside [low, high]
    ok = (close.notna() & adj.notna() & (close > 1e-4) & (adj > 0)
          & (high >= low) & (close <= high * 1.0001) & (close >= low * 0.9999))
    del close, adj, high, low
    b = b[ok]
    del ok
    b = b.sort_values(["date", "ticker"])
    return b.drop_duplicates(["date", "ticker"], keep="last", ignore_index=True)


def to_wide(bars: pd.DataFrame, field: str = "adj_close") -> pd.DataFrame:
    """date x ticker matrix for one field."""
    return to_wide_many(bars, [field])[field]


def to_wide_many(bars: pd.DataFrame, fields: list[str]) -> dict[str, pd.DataFrame]:
    """date x ticker matrices for several fields of clean bars (one row per date and ticker, as clean_bars leaves
    them). Same result as bars.pivot(index="date", columns="ticker", values=field).sort_index() for each field,
    but the date and ticker positions are worked out once and each matrix is filled directly, without pivot's
    intermediate copies (pivot on the live job's ~12k tickers was a large part of its memory peak)."""
    d_codes, dates = pd.factorize(bars["date"], sort=True)
    t_codes, tickers = pd.factorize(bars["ticker"], sort=True)
    if (d_codes < 0).any() or (t_codes < 0).any():
        raise ValueError("bars have a missing date or ticker")
    index = pd.DatetimeIndex(dates, name="date") if not isinstance(dates, pd.DatetimeIndex) else dates.rename("date")
    columns = pd.Index(tickers, name="ticker")
    out = {}
    for f in fields:
        vals = bars[f].to_numpy()
        arr = np.full((len(index), len(columns)), np.nan, dtype=vals.dtype if vals.dtype.kind == "f" else "float64")
        arr[d_codes, t_codes] = vals
        out[f] = pd.DataFrame(arr, index=index, columns=columns, copy=False)
    return out


def today_str() -> str:
    return date.today().isoformat()
