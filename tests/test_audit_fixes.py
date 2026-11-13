"""Tests for the 2026-11-13 bug-audit fixes on the live path: contiguous quarter grid, expiring fundamentals,
ticker mapping that rejects older companies, data-freshness check, account-weight start (no-trade band),
untouched names not traded, opening-auction full exits and wait window, paginated order fetch."""
import importlib.util
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from src.broker import PaperBroker
from src.fundamentals import EXPIRE_DAYS, align_to_prices, daily_panels, quarterly_features, regularize_quarters
from src.providers_sharadar import map_tickers
from tests.test_broker import _broker, _StubClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("run_daily_mod", ROOT / "scripts" / "run_daily.py")
rd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rd)
ET = ZoneInfo("America/New_York")


def _rows(periods, eps=None, drop=()):
    """Quarterly ARQ-like rows: report periods every quarter end, filing 35 days later; `drop` = missing quarters."""
    rp = pd.date_range("2015-03-31", periods=periods, freq="QE")
    n = len(rp)
    eps = np.arange(n, dtype=float) if eps is None else np.asarray(eps, dtype=float)
    d = pd.DataFrame({"ticker": "X", "reportperiod": rp, "date": rp + pd.Timedelta(days=35), "eps": eps, "epsdil": eps,
                      "revenue": 100.0, "cor": 40.0, "netinc": 10.0, "netinccmn": 10.0, "ncfo": 12.0, "fcf": 8.0,
                      "assets": 1000.0, "equity": 500.0, "marketcap": 2000.0, "sharesbas": 50.0})
    return d.drop(index=list(drop)).reset_index(drop=True)


def test_regularize_inserts_a_nan_row_for_a_missing_quarter():
    g = regularize_quarters(_rows(12, drop=[6]))
    assert len(g) == 12 and g["date"].isna().sum() == 1 and pd.isna(g.loc[6, "date"])
    assert regularize_quarters(_rows(5)) is None                                   # too short


def test_missing_quarter_makes_ttm_and_yoy_nan_instead_of_stitching():
    full, gap = quarterly_features(_rows(16)), quarterly_features(_rows(16, drop=[8]))
    assert len(gap) == 15                                                          # the inserted quarter is dropped
    # TTM sums that would span the gap (quarters 8..11) are NaN, not a 4-row sum over 5 quarters
    after = gap.index > _rows(16)["date"][8]
    assert gap.loc[after, "gprof"].iloc[:3].isna().all() and gap.loc[after, "gprof"].iloc[3:].notna().all()
    # year-ago EPS change 4 QUARTERS back: quarter 12's sue uses quarter 8, which is missing -> NaN
    q12 = _rows(16)["date"][12]
    assert np.isnan(gap.loc[q12, "sue"])
    # rows far from the gap are identical to the no-gap history
    q3 = _rows(16)["date"][3]
    assert gap.loc[q3, "gprof"] == full.loc[q3, "gprof"]


def test_align_to_prices_lets_a_value_expire():
    q = quarterly_features(_rows(8))
    days = pd.bdate_range("2016-01-01", "2019-12-31")
    panel = daily_panels({"X": q}, days, features=("gprof",))["gprof"]
    close = pd.DataFrame({"X": 1.0, "Y": 1.0}, index=days)
    panel["Y"] = 0.5                                                               # another name with data every day
    w = align_to_prices(panel, close)
    last = q.index.max()
    gone = days[days > last + pd.Timedelta(days=EXPIRE_DAYS + 10)]
    assert np.allclose(w.loc[gone, "X"], 0.5)                                      # expired -> the day's median (= Y)


def test_map_tickers_rejects_a_company_that_stopped_trading_before_the_name_began():
    tk = pd.DataFrame({"ticker": ["FOX1", "FOXA", "ABC", "ABC1"], "isdelisted": ["Y", "N", "N", "Y"],
                       "lastpricedate": pd.to_datetime(["2019-03-19", "2026-11-12", "2026-11-12", "2008-01-01"])})
    m = map_tickers(["FOX", "ABC"], tk, first_dates={"FOX": pd.Timestamp("2019-03-13"), "ABC": pd.Timestamp("2010-01-04")})
    assert m["FOX"] == "FOX1"                                                      # ended 6 days after: still a candidate
    m2 = map_tickers(["FOX"], tk, first_dates={"FOX": pd.Timestamp("2019-04-01")})
    assert "FOX" not in m2                                                         # ended 13 days before: rejected
    assert m["ABC"] == "ABC"                                                       # exact live ticker wins
    assert map_tickers(["FOX"], tk)["FOX"] == "FOX1"                               # old behaviour without first dates


def test_expected_last_session_and_check_data():
    s = [date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12), date(2026, 11, 13)]
    assert rd.expected_last_session(datetime(2026, 11, 13, 17, 30, tzinfo=ET), s) == date(2026, 11, 13)
    assert rd.expected_last_session(datetime(2026, 11, 13, 9, 0, tzinfo=ET), s) == date(2026, 11, 12)
    idx = pd.bdate_range("2026-11-02", "2026-11-12")
    close = pd.DataFrame(1.0, index=idx, columns=list("ABCDEFGHIJ"))
    rd.check_data(close, date(2026, 11, 12))
    with pytest.raises(rd.DataNotCurrent, match="ends 2026-11-12"):
        rd.check_data(close, date(2026, 11, 13))
    part = close.copy()
    part.iloc[-1, :5] = np.nan
    with pytest.raises(rd.DataNotCurrent, match="partial"):
        rd.check_data(part, date(2026, 11, 12))


def test_wait_for_opg_window():
    waited = []
    assert rd.wait_for_opg_window(lambda: datetime(2026, 11, 13, 18, 31, tzinfo=ET), waited.append) == 30 * 60
    assert waited == [30 * 60]
    assert rd.wait_for_opg_window(lambda: datetime(2026, 11, 13, 19, 5, tzinfo=ET), waited.append) == 0.0
    assert rd.wait_for_opg_window(lambda: datetime(2026, 11, 14, 8, 0, tzinfo=ET), waited.append) == 0.0


def test_account_weights_and_drift():
    pos = pd.Series({"A": 30_000.0, "B": 20_000.0, "IEF": 25_000.0})
    w = rd.account_weights(pos, 100_000.0, {"IEF", "GLD"})
    assert w.to_dict() == {"A": 0.3, "B": 0.2}
    idx = pd.bdate_range("2026-11-02", periods=3)
    close = pd.DataFrame({"A": [10.0, 11.0, 11.0], "B": [10.0, 10.0, 5.0]}, index=idx)
    d = rd.drifted(pd.Series({"A": 0.5, "B": 0.5}), close, idx[0], idx[-1])
    # A +10%, B -50%: 0.55 / 0.25 of the start value, total 0.8
    assert np.allclose(d.values, [0.55 / 0.8, 0.25 / 0.8])


def test_band_keeps_drifted_weight_and_untouched_names_are_not_traded():
    from src.portfolio import Rules, State, rebalance
    rules = Rules(top_n=2, sizing="equal", max_weight=1.0, min_trade_pct=0.20, cash_buffer=0.0)
    scores = pd.Series({"A": 2.0, "B": 1.0, "C": 0.0})
    # A drifted from 0.50 to 0.55 (+10% < 20% band) -> held at 0.55, not traded back to 0.50
    new, trades, _ = rebalance(scores, None, rules, State(weights=pd.Series({"A": 0.55, "B": 0.45})), pd.Timestamp("2026-11-13"))
    assert new["A"] == 0.55 and "A" not in trades.index
    skip = {t for t in new.index if abs(new[t] - {"A": 0.55, "B": 0.45}[t]) < 1e-12}
    pb = PaperBroker(Path(__file__).parent / "_tmp_paper.json")
    pb.acct = {"cash": 0.0, "positions": {"A": {"qty": 550.0, "price": 100.0}, "B": {"qty": 450.0, "price": 100.0}}}
    pb.mark(pd.Series({"A": 101.0, "B": 100.0}))                                  # A moved after the decision
    orders = pb.submit_targets(new, pd.Series({"A": 101.0, "B": 100.0}), skip=skip)
    assert all(o["ticker"] not in skip for o in orders)
    Path(pb.path).unlink(missing_ok=True)


def test_opg_full_exit_sells_every_share_including_the_fraction():
    c = _StubClient({"A": 1050.0})                                                 # 10.5 shares at $100
    b = _broker(c, order_type="opg")
    b.submit_targets(pd.Series(dtype=float), pd.Series({"A": 100.0}))
    tif = [(r.symbol, float(r.qty), r.time_in_force.value) for r in c.reqs]
    assert ("A", 10.0, "opg") in tif and ("A", 0.5, "day") in tif


def test_skip_is_honoured_by_the_alpaca_broker():
    c = _StubClient({"A": 30_000.0, "B": 10_000.0})
    b = _broker(c)
    b.submit_targets(pd.Series({"A": 0.25, "B": 0.25}), pd.Series({"A": 100.0, "B": 100.0}), skip={"A"})
    assert [s for s, *_ in c.submitted] == ["B"]


def test_reconcile_pages_through_more_than_500_orders():
    spec = importlib.util.spec_from_file_location("rf", ROOT / "scripts" / "reconcile_fills.py")
    rf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rf)

    class O:
        def __init__(self, i):
            self.id, self.submitted_at = f"o{i}", pd.Timestamp("2026-11-01") + pd.Timedelta(minutes=i)

    allo = [O(i) for i in range(1234)]

    class C:
        def get_orders(self, req):
            a = pd.Timestamp(req.after)
            return [o for o in allo if o.submitted_at > a][: req.limit]

    class Req:
        def __init__(self, status, after, limit, direction):
            self.after, self.limit = after, limit

    got = rf.all_closed_orders(C(), pd.Timestamp("2026-10-31").to_pydatetime(), Req, type("S", (), {"CLOSED": "closed"}))
    assert len(got) == 1234 and len({o.id for o in got}) == 1234
