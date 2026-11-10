import numpy as np
import pandas as pd
import pytest

from src.features import compute_features
from src.fundamentals import EXPIRE_DAYS, align_to_prices, daily_column, daily_panels, quarterly_features
from src.providers_sharadar import map_tickers


def _rows(n=12, eps_growth=0.1, start="2015-03-31"):
    """n regular quarters of synthetic as-reported rows (Sharadar ARQ column names)."""
    rp = pd.date_range(start, periods=n, freq="QE-DEC")
    eps = np.array([1.0 * (1 + eps_growth) ** (i // 4) for i in range(n)])
    return pd.DataFrame({
        "reportperiod": rp, "date": rp + pd.Timedelta(days=40), "eps": eps, "epsdil": eps,
        "revenue": 100.0, "cor": 60.0, "netinc": 10.0, "netinccmn": 10.0, "ncfo": 12.0, "fcf": 8.0,
        "assets": 400.0, "equity": 200.0, "marketcap": 1000.0, "sharesbas": np.linspace(100, 90, n),
    })


def test_quarterly_features_definitions():
    q = quarterly_features(_rows())
    assert q is not None and q.index.name == "avail"
    assert q["gprof"].dropna().iloc[-1] == pytest.approx((400 - 240) / 400)        # ttm (rev - cogs) / assets
    assert q["accruals"].dropna().iloc[-1] == pytest.approx((40 - 48) / 400)
    assert q["fcf_yield"].dropna().iloc[-1] == pytest.approx(32 / 1000)
    assert q["roe"].dropna().iloc[-1] == pytest.approx(40 / 200)
    assert q["buyback"].dropna().iloc[-1] > 0                                      # shares fell -> positive
    assert q["asset_growth"].dropna().abs().max() < 1e-12                          # flat assets
    assert q["sue"].notna().sum() > 0                                              # needs 8 quarters of changes


def test_quarterly_features_drops_irregular_spacing_and_short_histories():
    r = _rows(n=5)
    assert quarterly_features(r) is None
    r = _rows(n=12)
    r.loc[6, "reportperiod"] = r.loc[6, "reportperiod"] + pd.Timedelta(days=40)   # irregular quarter: it and the
    assert len(quarterly_features(r)) == 10                                         # next (short-gap) row are dropped


def test_daily_column_carries_forward_and_expires():
    days = pd.bdate_range("2020-01-01", "2022-06-30")
    s = pd.Series({pd.Timestamp("2020-02-14"): 1.0, pd.Timestamp("2020-05-15"): 2.0})
    col = pd.Series(daily_column(s, days), index=days)
    assert np.isnan(col.loc["2020-02-13"]) and col.loc["2020-02-14"] == 1.0 and col.loc["2020-05-14"] == 1.0
    assert col.loc["2020-05-15"] == 2.0 and col.loc["2021-06-01"] == 2.0
    assert np.isnan(col.loc[pd.Timestamp("2020-05-15") + pd.Timedelta(days=EXPIRE_DAYS + 3):].iloc[0])


def test_daily_panels_and_alignment_fill_missing_names_with_median():
    days = pd.bdate_range("2015-01-01", "2019-12-31")
    panels = daily_panels({"AAA": quarterly_features(_rows()), "BBB": quarterly_features(_rows(eps_growth=0.5))}, days, features=("sue", "gprof"))
    assert set(panels) == {"sue", "gprof"} and list(panels["sue"].columns) == ["AAA", "BBB"]
    close = pd.DataFrame(1.0, index=pd.bdate_range("2017-01-02", "2019-12-31"), columns=["AAA", "BBB", "ZZZ"])
    a = align_to_prices(panels["gprof"], close)
    assert a.shape == close.shape and a.notna().all().all()
    assert a["ZZZ"].iloc[-1] == pytest.approx(a[["AAA", "BBB"]].iloc[-1].median())
    feats = compute_features(close, close * 1000, fundamentals={"gprof": panels["gprof"]})
    assert "gprof" in feats.columns and "mom_252_skip21" in feats.columns


def test_map_tickers_handles_live_and_delisted_norgate_names():
    tk = pd.DataFrame({
        "ticker": ["AAPL", "ABS", "AAI", "AAI1", "GM"],
        "isdelisted": ["N", "Y", "Y", "Y", "N"],
        "lastpricedate": pd.to_datetime(["2026-11-06", "2006-06-01", "2011-05-02", "1999-08-20", "2026-11-06"]),
    })
    m = map_tickers(["AAPL", "ABS-200606", "AAI-201105", "AAI-199908", "ZZZ-200101", "NOPE"], tk)
    assert m == {"AAPL": "AAPL", "ABS-200606": "ABS", "AAI-201105": "AAI", "AAI-199908": "AAI1"}
