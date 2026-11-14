"""Ports for the ranks 201-2500 model (2026-11-14): altz, point-in-time market cap, sqrt_mcap sizing, fresh entry,
the risk-parity sleeve and the value screen. Each mirrors a sweep rule; these tests pin the behaviour."""
import numpy as np
import pandas as pd
import pytest

from src.fundamentals import ARQ_COLUMNS, FEATURES, fresh_mask, mcap_true, quarterly_features
from src.portfolio import Rules, State, rebalance, select_top, size_positions
from src.ranking import apply_screen
from src.sleeve import sleeve_allocation


def _rows(n=12, **over):
    rp = pd.date_range("2018-03-31", periods=n, freq="QE")
    d = {c: np.nan for c in ARQ_COLUMNS}
    d = pd.DataFrame({c: [np.nan] * n for c in ARQ_COLUMNS})
    d["ticker"], d["dimension"] = "XYZ", "ARQ"
    d["reportperiod"] = rp
    d["date"] = rp + pd.Timedelta(days=40)
    d["calendardate"], d["lastupdated"] = rp, d["date"]
    base = dict(eps=1.0, epsdil=1.0, netinc=10.0, netinccmn=10.0, revenue=100.0, cor=60.0, ncfo=12.0, fcf=8.0,
                assets=400.0, equity=200.0, marketcap=500.0, sharesbas=50.0, ebit=15.0, liabilities=200.0,
                workingcapital=40.0, retearn=80.0, assetsc=150.0, liabilitiesc=110.0)
    for k, v in {**base, **over}.items():
        d[k] = v
    d["eps"] = d["epsdil"] = 1.0 + 0.1 * np.arange(n) + 0.05 * (np.arange(n) % 3)
    return d


def test_altz_matches_the_formula():
    assert "altz" in FEATURES and {"liabilities", "workingcapital", "retearn"} <= set(ARQ_COLUMNS)
    q = quarterly_features(_rows())
    want = 1.2 * 40 / 400 + 1.4 * 80 / 400 + 3.3 * 60 / 400 + 0.6 * 500 / 200 + 1.0 * 400 / 400
    got = q["altz"].dropna()
    assert len(got) == 12 - 3                       # trailing-4Q sums need four quarters
    assert np.allclose(got.values, want)


def test_altz_clipped_and_missing_liabilities():
    q = quarterly_features(_rows(marketcap=1e9))
    assert q["altz"].dropna().max() == 20.0
    q = quarterly_features(_rows(liabilities=0.0))   # TL = 0 -> NaN, not inf
    assert q["altz"].isna().all()


def test_mcap_true_anchor_carry_expiry_and_takeover():
    idx = pd.bdate_range("2020-01-01", "2021-12-31")
    adj = pd.DataFrame({"A": np.linspace(10, 30, len(idx)), "B": 5.0}, index=idx)
    fil = {"A": pd.DataFrame({"date": pd.to_datetime(["2020-01-04", "2020-06-15"]), "marketcap": [100.0, 400.0]}),
           "B": pd.DataFrame({"date": pd.to_datetime(["2020-02-03"]), "marketcap": [50.0]})}
    m = mcap_true(fil, adj)
    a0 = idx[idx <= "2020-01-04"][-1]                # Saturday filing: anchored on Friday's close
    assert m.loc[:a0, "A"].iloc[:-1].isna().all() and m.loc[a0, "A"] == 100.0
    t = pd.Timestamp("2020-03-02")
    assert np.isclose(m.loc[t, "A"], 100.0 * adj.loc[t, "A"] / adj.loc[a0, "A"])
    assert m.loc["2020-06-15", "A"] == 400.0         # the next filing takes over on its own anchor day
    assert m.loc["2021-07-21":, "A"].isna().all()     # 400 days after 2020-06-15 it expires
    assert m.loc["2020-06-15", "B"] == 50.0 and m.loc["2021-03-10":, "B"].isna().all()


def test_sqrt_mcap_sizing():
    s = pd.Series([3.0, 2.0, 1.0], index=["A", "B", "C"])
    r = Rules(top_n=3, sizing="sqrt_mcap", max_weight=1.0, cash_buffer=0.0, mcap=pd.Series({"A": 400.0, "B": 100.0}))
    w = size_positions(s, None, r)
    # C has no market cap: it gets the median of the chosen names (250)
    raw = np.sqrt([400.0, 100.0, 250.0])
    assert np.allclose(w.values, raw / raw.sum())
    with pytest.raises(ValueError):
        size_positions(s, None, Rules(top_n=3, sizing="sqrt_mcap"))


def test_fresh_entry_blocks_new_names_only():
    s = pd.Series([5.0, 4.0, 3.0, 2.0], index=["A", "B", "C", "D"])
    fresh = pd.Series({"A": False, "B": True, "C": False})        # D unknown -> not fresh
    r = Rules(top_n=3, sizing="equal", max_weight=1.0, cash_buffer=0.0, reentry_cooldown_days=0, fresh=fresh)
    held = State(weights=pd.Series({"C": 0.3}))
    sel = select_top(s, r, held, pd.Timestamp("2026-11-16"))
    assert list(sel.index) == ["B", "C"]                # A not fresh and not held; C held stays
    w, trades, _ = rebalance(s, None, r, held, pd.Timestamp("2026-11-16"))
    assert set(w.index) == {"B", "C"}


def test_fresh_mask_counts_trading_days_since_change():
    idx = pd.bdate_range("2026-01-01", periods=40)
    sue = pd.DataFrame({"A": 1.0, "B": np.nan}, index=idx)
    sue.loc[idx[10]:, "A"] = 2.0                         # new filing on day 10
    f = fresh_mask(sue, pd.DataFrame(index=idx, columns=["A", "B"], dtype=float), 21)
    assert f.loc[idx[10], "A"] and f.loc[idx[31], "A"] and not f.loc[idx[32], "A"]
    assert not f["B"].any()


def test_rp_sleeve_inverse_vol():
    idx = pd.bdate_range("2020-01-01", periods=120)
    rng = np.random.default_rng(1)
    px = pd.DataFrame({"IEF": np.cumprod(1 + rng.normal(0, 0.003, len(idx))),
                       "GLD": np.cumprod(1 + rng.normal(0, 0.009, len(idx)))}, index=idx)
    w = sleeve_allocation(px, "rp")
    assert np.allclose(w.iloc[:40].values, 0.5)        # fewer than 40 returns: equal split
    assert np.allclose(w.sum(axis=1), 1.0)
    vol = px.pct_change().rolling(63, min_periods=40).std().iloc[-1]
    assert np.isclose(w.iloc[-1]["IEF"] / w.iloc[-1]["GLD"], vol["GLD"] / vol["IEF"])
    assert w.iloc[-1]["IEF"] > 0.6


def test_value_screen():
    s = pd.Series([3.0, 2.0, 1.0], index=["A", "B", "C"])
    f = pd.DataFrame({"altz": [1.0, 2.5, np.nan]}, index=["A", "B", "C"])
    assert list(apply_screen(s, f, {"feat": "altz", "min": 1.81}).index) == ["B", "C"]
    assert apply_screen(s, f, None) is s
    with pytest.raises(ValueError):
        apply_screen(s, f, {"feat": "altz", "cut": 0.2})
    with pytest.raises(ValueError):
        apply_screen(s, f, {"feat": "nope", "min": 0})
