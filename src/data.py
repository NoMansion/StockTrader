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
                bars.to_parquet(cache, index=False)
            _remember(missing)
    else:
        bars = PROVIDERS[provider](tickers, start, end)
        bars.to_parquet(cache, index=False)
        attempted_file.write_text(json.dumps(sorted(set(tickers))))

    bars = bars[bars["ticker"].isin(tickers)].copy()
    bars["date"] = pd.to_datetime(bars["date"])
    return clean_bars(bars)


def clean_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Minimal hygiene. The full pipeline is specified in DATA_PLAN.md."""
    b = bars.copy()
    for c in ["open", "high", "low", "close", "volume", "adj_close"]:
        b[c] = pd.to_numeric(b[c], errors="coerce").astype("float64")   # never let object dtype through
    b = b.dropna(subset=["close", "adj_close"])
    # Norgate stores 0.000001 as a "no trade" placeholder on some OTC names;
    # a bar at that price is not a price, and the return off it is +1e8%.
    b = b[(b["close"] > 1e-4) & (b["adj_close"] > 0)]
    # bad prints: high < low or close outside [low, high]
    ok = (b["high"] >= b["low"]) & (b["close"] <= b["high"] * 1.0001) & (b["close"] >= b["low"] * 0.9999)
    b = b[ok]
    b = b.sort_values(["date", "ticker"]).drop_duplicates(["date", "ticker"], keep="last")
    return b.reset_index(drop=True)


def to_wide(bars: pd.DataFrame, field: str = "adj_close") -> pd.DataFrame:
    """date x ticker matrix for one field."""
    return bars.pivot(index="date", columns="ticker", values=field).sort_index()


def today_str() -> str:
    return date.today().isoformat()
