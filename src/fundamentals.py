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
  round 38 sweep features (definitions identical to the sweep's sharadar_build3.py):
    sur           revenue surprise: revenue per share minus four quarters earlier, scaled like sue
    ebitda_ev     trailing-4Q EBITDA / enterprise value
    sp            trailing-4Q revenue / market cap
    opprof        trailing-4Q (revenue - COGS - SG&A - interest) / book equity
    roic          trailing-4Q EBIT / invested capital
    fscore        Piotroski F-score (0-9)

A value becomes known on its filing date (`avail`) and expires EXPIRE_DAYS later if nothing
newer arrived. Input rows follow Sharadar's SF1 ARQ column names (one row per fiscal quarter):
    reportperiod, date (filing date), eps, epsdil, revenue, cor, netinc, netinccmn, ncfo, fcf,
    assets, equity, marketcap, sharesbas, plus (round 38 features) sgna, intexp, ebit, ebitda, ev,
    assetsc, liabilitiesc, debt, debtnc, invcap, shareswa, plus (round 41, the altz screen) liabilities,
    workingcapital, retearn

Round 41 (2026-11-14, live since the ranks 201-2500 switch): altz = Altman Z-score with the market value of equity,
    1.2 WC/A + 1.4 RE/A + 3.3 EBIT_ttm/A + 0.6 MVE/TL + 1.0 Sales_ttm/A, clipped to [-10, 20] (< 1.81 = distress zone),
    exactly as the sweep's sharadar_build5_v2.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES_R38 = ("sur", "ebitda_ev", "sp", "opprof", "roic", "fscore")
FEATURES_R41 = ("altz",)
FEATURES = ("sue", "gprof", "ni_growth", "accruals", "fcf_yield", "ep", "sales_growth", "asset_growth", "buyback", "roe",
            "fcf_assets") + FEATURES_R38 + FEATURES_R41
EXPIRE_DAYS = 400
R38_COLUMNS = ["sgna", "intexp", "ebit", "ebitda", "ev", "assetsc", "liabilitiesc", "debt", "debtnc", "invcap", "shareswa"]
R41_COLUMNS = ["liabilities", "workingcapital", "retearn"]
ARQ_COLUMNS = ["ticker", "dimension", "calendardate", "date", "reportperiod", "lastupdated", "eps", "epsdil", "netinc",
               "netinccmn", "revenue", "cor", "ncfo", "fcf", "assets", "equity", "marketcap", "sharesbas"] + R38_COLUMNS + R41_COLUMNS


def _nz(s: pd.Series) -> pd.Series:
    return s.replace(0, np.nan)


def _r38_features(d: pd.DataFrame) -> pd.DataFrame:
    """The six round 38 features on the de-duplicated quarterly rows `d` (index reportperiod), exactly as the
    sweep's sharadar_build3.py computes them."""
    ttm = {n: d[n].rolling(4, min_periods=4).sum()
           for n in ("revenue", "cor", "sgna", "intexp", "ebit", "ebitda", "netinc", "ncfo")}
    assets = _nz(d["assets"]).ffill(limit=2)
    mcap = _nz(d["marketcap"]).ffill(limit=2)
    equity = d["equity"].where(d["equity"] > 0).ffill(limit=2)
    ev = d["ev"].where(d["ev"] > 0).ffill(limit=2)
    invcap = d["invcap"].where(d["invcap"] > 0).ffill(limit=2)
    shares = _nz(d["shareswa"]).fillna(d["sharesbas"]).ffill(limit=2)
    o = pd.DataFrame(index=d.index)
    o["ebitda_ev"] = ttm["ebitda"] / ev
    o["sp"] = ttm["revenue"] / mcap
    rps = d["revenue"] / shares
    chr_ = rps - rps.shift(4)
    o["sur"] = chr_ / _nz(chr_.rolling(8, min_periods=6).std())
    roa = ttm["netinc"] / assets
    gm = (ttm["revenue"] - ttm["cor"]) / _nz(ttm["revenue"]).where(ttm["revenue"] > 0)
    ato = ttm["revenue"] / assets
    d_roa, d_gm, d_ato = roa - roa.shift(4), gm - gm.shift(4), ato - ato.shift(4)
    cfo_a = ttm["ncfo"] / assets
    lev_r = d["debtnc"].fillna(d["debt"]) / assets
    cur = d["assetsc"] / _nz(d["liabilitiesc"])
    f = pd.DataFrame({"roa_pos": roa > 0, "cfo_pos": cfo_a > 0, "droa_pos": d_roa > 0, "accrual": cfo_a > roa,
                      "dlev": lev_r < lev_r.shift(4), "dcur": cur > cur.shift(4),
                      "noiss": d["sharesbas"] <= d["sharesbas"].shift(4), "dgm": d_gm > 0, "dato": d_ato > 0}, index=d.index)
    ok = roa.notna() & roa.shift(4).notna() & cfo_a.notna()
    o["fscore"] = f.sum(axis=1).astype("float64").where(ok)
    o["roic"] = ttm["ebit"] / invcap
    o["opprof"] = (ttm["revenue"] - ttm["cor"] - ttm["sgna"].fillna(0) - ttm["intexp"].fillna(0)) / equity
    return o


def _r41_features(d: pd.DataFrame) -> pd.DataFrame:
    """altz on the regularized quarterly rows `d`, exactly as the sweep's sharadar_build5_v2.py computes it."""
    ttm = {n: d[n].rolling(4, min_periods=4).sum() for n in ("ebit", "revenue")}
    A = _nz(d["assets"]).ffill(limit=2)
    mve = _nz(d["marketcap"]).ffill(limit=2)
    o = pd.DataFrame(index=d.index)
    o["altz"] = (1.2 * d["workingcapital"] / A + 1.4 * d["retearn"] / A + 3.3 * ttm["ebit"] / A
                 + 0.6 * mve / _nz(d["liabilities"]) + 1.0 * ttm["revenue"] / A).clip(-10, 20)
    return o


QDAYS = 91.3125


def regularize_quarters(rows: pd.DataFrame, min_rows: int = 6) -> pd.DataFrame | None:
    """One company's quarterly rows on a CONTIGUOUS fiscal-quarter grid (index = quarter number).

    Keeps the first filing per report period. Each kept row gets a quarter number from the gap to the previous kept
    row (gap / 91.3 days, rounded, at least 1); a row less than 75 days after the previous one is dropped. The frame
    is then reindexed to every quarter, so a quarter the company never reported is a NaN row: trailing-4-quarter sums
    and year-ago comparisons that need it become NaN instead of silently spanning five quarters (bug audit
    2026-11-13; the old rule just dropped irregular rows and stitched over the gap). Inserted rows have no filing
    `date`. Identical to the sweep's fund_common.regularize."""
    d = rows.sort_values(["reportperiod", "date"]).drop_duplicates("reportperiod", keep="first")
    rp = d["reportperiod"].values
    keep, qn, last, q = [], [], None, 0
    for i, r in enumerate(rp):
        if last is None:
            keep.append(i); qn.append(0); last = r
            continue
        gap = (r - last) / np.timedelta64(1, "D")
        if gap < 75:
            continue
        q += max(1, int(round(gap / QDAYS)))
        keep.append(i); qn.append(q); last = r
    if len(keep) < min_rows:
        return None
    d = d.iloc[keep].copy()
    d.index = pd.Index(qn, name="q")
    return d.reindex(pd.RangeIndex(qn[-1] + 1, name="q"))


def quarterly_features(rows: pd.DataFrame) -> pd.DataFrame | None:
    """Per-quarter features for one company, indexed by availability (filing) date.
    Keeps the first filing per report period, on a contiguous quarter grid (regularize_quarters)."""
    d = regularize_quarters(rows)
    if d is None:
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
    if all(c in d.columns for c in R38_COLUMNS):
        r38 = _r38_features(d)
        for k in FEATURES_R38:
            out[k] = r38[k]
    if all(c in d.columns for c in R41_COLUMNS + ["ebit"]):
        out["altz"] = _r41_features(d)["altz"]
    out = out.replace([np.inf, -np.inf], np.nan)
    out.index = pd.DatetimeIndex(t["avail"].values, name="avail")
    return out[out.index.notna()].sort_index()          # drop the inserted (never reported) quarters


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
    cross-sectional median (a neutral rank) so coverage gaps do not shrink the universe.
    The panel already carries each value until the next filing or EXPIRE_DAYS; the forward fill here only bridges
    calendar mismatches (at most 5 rows), so an expired value stays expired (bug audit 2026-11-13: an unlimited
    ffill carried every expired filing forward forever)."""
    w = panel.reindex(index=close.index.union(panel.index), columns=close.columns).ffill(limit=5).reindex(close.index)
    med = w.median(axis=1)
    return w.T.fillna(med).T.astype("float32")


def mcap_true(filings: dict[str, pd.DataFrame], adj: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time market cap, date x symbol on `adj`'s calendar (the sweep's alt/mcap_build.py, sqrt_mcap sizing).

    Sharadar `marketcap` on a filing (datekey) is correct point in time; carry it forward by the adjusted price:
        mcap(t) = marketcap(last filing k with datekey <= t) x adj(t) / adj(anchor_k),
    anchor_k = the last trading day <= datekey_k. A value holds from its anchor until the next filing's anchor or
    EXPIRE_DAYS after its datekey (exclusive), whichever is first. `filings`: symbol -> rows with `date` (datekey)
    and `marketcap`."""
    idx = adj.index
    M = np.full(adj.shape, np.nan, dtype="float64")
    ci = {c: j for j, c in enumerate(adj.columns)}
    for sym, g in filings.items():
        j = ci.get(sym)
        if j is None or g is None or not len(g):
            continue
        g = g[g["marketcap"] > 0].sort_values("date").drop_duplicates("date", keep="last")
        a = adj.iloc[:, j].to_numpy(dtype="float64")
        dk = pd.to_datetime(g["date"]).to_numpy()
        mc = g["marketcap"].to_numpy(dtype="float64")
        pos = idx.searchsorted(dk, side="right") - 1
        for k in range(len(g)):
            pk = pos[k]
            if pk < 0 or not np.isfinite(a[pk]) or a[pk] <= 0:
                continue
            stop = idx.searchsorted(dk[k] + np.timedelta64(EXPIRE_DAYS, "D"), side="right")
            if k + 1 < len(g):
                stop = min(stop, pos[k + 1])
            if stop <= pk:
                continue
            M[pk:stop, j] = mc[k] * a[pk:stop] / a[pk]
    return pd.DataFrame(M, index=idx, columns=adj.columns)


def fresh_mask(sue: pd.DataFrame, close: pd.DataFrame, days: int) -> pd.DataFrame:
    """date x ticker bool: True within `days` trading days of the day the name's SUE last changed (its last filing),
    on `close`'s calendar and columns. Names that never had a SUE are never fresh. The sweep's fresh_entry (built
    from the un-lagged daily SUE panel, as here)."""
    p = sue.reindex(index=close.index.union(sue.index), columns=close.columns).ffill(limit=5).reindex(close.index)
    chg = (p.ne(p.shift()) & p.notna()).to_numpy()
    pos = np.arange(len(p))[:, None] * np.ones((1, p.shape[1]))
    last = pd.DataFrame(np.where(chg, pos, np.nan), index=p.index, columns=p.columns).ffill()
    return (pd.DataFrame(pos, index=p.index, columns=p.columns) - last) <= int(days)
