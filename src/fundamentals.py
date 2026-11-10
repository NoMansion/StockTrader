"""Point-in-time fundamental features from as-reported quarterly rows.

Shared by the research sweep and the live pipeline so both use one definition:
    sue           EPS (diluted) minus EPS four quarters earlier, scaled by the 8-quarter std of that change
    gprof         trailing-4Q (revenue - cost of revenue) / total assets
    ni_growth     change in trailing-4Q net income vs a year earlier / total assets
    accruals      trailing-4Q (net income - operating cash flow) / total assets   (lower is better)
    fcf_yield     trailing-4Q free cash flow / market cap
    ep            trailing-4Q net income to common / market cap
    sales_growth  trailing-4Q revenue vs a year earlier
    asset_growth  total assets vs a year earlier                                 (lower is better)
    buyback       minus the change in basic shares vs a year earlier
    roe           trailing-4Q net income / book equity
    fcf_assets    trailing-4Q free cash flow / total assets

A value becomes known on its filing date (`avail`) and expires EXPIRE_DAYS later if nothing
newer arrived. Input rows follow Sharadar's SF1 ARQ column names (one row per fiscal quarter):
    reportperiod, date (filing date), eps, epsdil, revenue, cor, netinc, netinccmn, ncfo, fcf,
    assets, equity, marketcap, sharesbas
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = ("sue", "gprof", "ni_growth", "accruals", "fcf_yield", "ep", "sales_growth", "asset_growth", "buyback", "roe", "fcf_assets")
EXPIRE_DAYS = 400
ARQ_COLUMNS = ["ticker", "dimension", "calendardate", "date", "reportperiod", "lastupdated", "eps", "epsdil", "netinc",
               "netinccmn", "revenue", "cor", "ncfo", "fcf", "assets", "equity", "marketcap", "sharesbas"]


def quarterly_features(rows: pd.DataFrame) -> pd.DataFrame | None:
    """Per-quarter features for one company, indexed by availability (filing) date.
    Keeps the first filing per report period and only regular quarterly spacing."""
    d = rows.sort_values(["reportperiod", "date"]).drop_duplicates("reportperiod", keep="first").set_index("reportperiod")
    gap = d.index.to_series().diff().dt.days
    d = d[(gap.isna()) | ((gap >= 75) & (gap <= 110))]
    if len(d) < 6:
        return None
    eps = d["epsdil"].where(d["epsdil"].notna(), d["eps"])
    t = pd.DataFrame({"eps": eps, "rev": d["revenue"], "cogs": d["cor"], "ni": d["netinc"], "ocf": d["ncfo"], "fcf": d["fcf"],
                      "nic": d["netinccmn"], "assets": d["assets"], "equity": d["equity"], "mcap": d["marketcap"],
                      "shares": d["sharesbas"], "avail": d["date"]})
    for n in ("rev", "cogs", "ni", "ocf", "fcf", "nic"):
        t[f"{n}_ttm"] = t[n].rolling(4, min_periods=4).sum()
    assets = t["assets"].replace(0, np.nan).ffill(limit=2)
    mcap = t["mcap"].replace(0, np.nan).ffill(limit=2)
    equity = t["equity"].where(t["equity"] > 0).ffill(limit=2)
    out = pd.DataFrame(index=t.index)
    ch = t["eps"] - t["eps"].shift(4)
    out["sue"] = ch / ch.rolling(8, min_periods=6).std().replace(0, np.nan)
    out["gprof"] = (t["rev_ttm"] - t["cogs_ttm"]) / assets
    out["ni_growth"] = (t["ni_ttm"] - t["ni_ttm"].shift(4)) / assets
    out["accruals"] = (t["ni_ttm"] - t["ocf_ttm"]) / assets
    out["fcf_yield"] = t["fcf_ttm"] / mcap
    out["ep"] = t["nic_ttm"] / mcap
    out["sales_growth"] = t["rev_ttm"] / t["rev_ttm"].shift(4).replace(0, np.nan) - 1
    out["asset_growth"] = t["assets"] / t["assets"].shift(4).replace(0, np.nan) - 1
    out["buyback"] = -(t["shares"] / t["shares"].shift(4).replace(0, np.nan) - 1)
    out["roe"] = t["ni_ttm"] / equity
    out["fcf_assets"] = t["fcf_ttm"] / assets
    out = out.replace([np.inf, -np.inf], np.nan)
    out.index = pd.DatetimeIndex(t["avail"].values, name="avail")
    return out.sort_index()


def daily_column(s: pd.Series, days: pd.DatetimeIndex) -> np.ndarray:
    """Values keyed by filing date -> daily float32 array on `days`, carried forward, expiring after EXPIRE_DAYS."""
    s = s.dropna()
    s = s[~s.index.duplicated(keep="last")]
    col = np.full(len(days), np.nan, dtype="float32")
    if s.empty:
        return col
    pos = days.searchsorted(s.index, side="left")
    vals = s.values.astype("float32")
    stamps = s.index.values
    for i in range(len(s)):
        start = pos[i]
        if start >= len(days):
            break
        end = pos[i + 1] if i + 1 < len(s) else len(days)
        expire = days.searchsorted(stamps[i] + np.timedelta64(EXPIRE_DAYS, "D"), side="right")
        col[start:min(end, expire)] = vals[i]
    return col


def daily_panels(quarterly: dict[str, pd.DataFrame], days: pd.DatetimeIndex,
                 features: tuple[str, ...] = FEATURES) -> dict[str, pd.DataFrame]:
    """{feature: date x ticker float32 DataFrame} from per-ticker quarterly frames."""
    syms = sorted(quarterly)
    out = {}
    for k in features:
        arr = np.full((len(days), len(syms)), np.nan, dtype="float32")
        for j, sym in enumerate(syms):
            if k in quarterly[sym].columns:
                arr[:, j] = daily_column(quarterly[sym][k], days)
        out[k] = pd.DataFrame(arr, index=days, columns=syms)
    return out


def align_to_prices(panel: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """Reindex a feature panel onto the price matrix. Names without data get that day's
    cross-sectional median (a neutral rank) so coverage gaps do not shrink the universe."""
    w = panel.reindex(index=close.index.union(panel.index), columns=close.columns).ffill().reindex(close.index)
    med = w.median(axis=1)
    return w.T.fillna(med).T.astype("float32")
