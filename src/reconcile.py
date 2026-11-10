"""Live-vs-backtest fill reconciliation.

The backtest fills every order at the next day's open and charges a flat 10 bps. This module
compares Alpaca's actual fills (from the ids in data/orders.log) with the Norgate open and prior
close of the fill day, in basis points, signed so that positive = worse than the reference.

    orders_from_log(path)            -> DataFrame[id, ticker, side, notional, submit_date]
    fills_frame(alpaca_orders, log)  -> DataFrame[id, ticker, side, qty, price, filled_at, fill_date, ...]
    slippage(fills, bars)            -> adds open, prev_close, bps_open, bps_close
    summarize(sl)                    -> dict of aggregate statistics
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


def orders_from_log(path: str | Path = "data/orders.log", days: int | None = None) -> pd.DataFrame:
    rows = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        for o in rec["orders"]:
            if o.get("id"):
                rows.append({"id": o["id"], "ticker": o["ticker"], "side": o["side"], "notional": o.get("notional"),
                             "tif": o.get("tif", "day"), "submit_date": pd.Timestamp(rec["date"])})
    df = pd.DataFrame(rows, columns=["id", "ticker", "side", "notional", "tif", "submit_date"])
    if days is not None and len(df):
        df = df[df["submit_date"] >= df["submit_date"].max() - pd.Timedelta(days=days)]
    return df.reset_index(drop=True)


def fills_frame(alpaca_orders, log: pd.DataFrame) -> pd.DataFrame:
    """Join Alpaca order objects (alpaca-py `Order`) onto the log by id; filled orders only."""
    by_id = {str(o.id): o for o in alpaca_orders}
    rows = []
    for r in log.itertuples(index=False):
        o = by_id.get(r.id)
        if o is None:
            continue
        status = str(getattr(o.status, "value", o.status))
        if o.filled_qty is None or float(o.filled_qty) == 0 or o.filled_avg_price is None:
            rows.append({"id": r.id, "ticker": r.ticker, "side": r.side, "tif": r.tif, "submit_date": r.submit_date,
                         "status": status, "qty": 0.0, "price": np.nan, "filled_at": pd.NaT})
            continue
        filled_at = pd.Timestamp(o.filled_at)
        if filled_at.tzinfo is not None:
            filled_at = filled_at.tz_convert("America/New_York").tz_localize(None)
        rows.append({"id": r.id, "ticker": r.ticker, "side": r.side, "tif": r.tif, "submit_date": r.submit_date,
                     "status": status, "qty": float(o.filled_qty), "price": float(o.filled_avg_price), "filled_at": filled_at})
    f = pd.DataFrame(rows)
    if len(f):
        f["fill_date"] = f["filled_at"].dt.normalize()
        f["value"] = f["qty"] * f["price"]
    return f


def slippage(fills: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """`bars`: long table with date, ticker, open, close (unadjusted). Adds the fill day's open,
    the prior close and the signed slippage in bps (buy: fill above reference is positive)."""
    f = fills[fills["qty"] > 0].copy()
    if f.empty:
        return f.assign(open=np.nan, prev_close=np.nan, bps_open=np.nan, bps_close=np.nan)
    b = bars.sort_values(["ticker", "date"]).copy()
    b["prev_close"] = b.groupby("ticker")["close"].shift(1)
    ref = b[["date", "ticker", "open", "prev_close"]].rename(columns={"date": "fill_date"})
    f = f.merge(ref, on=["fill_date", "ticker"], how="left")
    sign = np.where(f["side"].str.lower() == "buy", 1.0, -1.0)
    f["bps_open"] = sign * (f["price"] / f["open"] - 1) * 1e4
    f["bps_close"] = sign * (f["price"] / f["prev_close"] - 1) * 1e4
    return f


def summarize(sl: pd.DataFrame, model_bps: float = 10.0) -> dict:
    ok = sl.dropna(subset=["bps_open"])
    if ok.empty:
        return {"orders": int(len(sl)), "priced": 0}
    w = ok["value"] / ok["value"].sum()
    out = {
        "orders": int(len(sl)), "priced": int(len(ok)), "notional": float(ok["value"].sum()),
        "bps_open_mean": float(ok["bps_open"].mean()), "bps_open_median": float(ok["bps_open"].median()),
        "bps_open_weighted": float((ok["bps_open"] * w).sum()),
        "bps_close_weighted": float((ok["bps_close"] * w).sum()),
        "share_filled_within_5min_of_open": float((ok["filled_at"].dt.time <= pd.Timestamp("09:35").time()).mean()),
        "model_bps": model_bps,
    }
    out["excess_vs_model_bps"] = out["bps_open_weighted"] - model_bps
    return out
