import pandas as pd
import pytest

from src.tracking import load_snapshots, model_day, save_snapshot, summarize, track


def px(**kw):
    return pd.Series(kw, dtype="float64")


def test_no_trade_day_is_just_the_holdings_return():
    h = px(A=0.5, B=0.3)
    m = model_day(h, h, skip={"A", "B"}, prev_close=px(A=100, B=50), open_=px(A=100, B=50), close=px(A=110, B=45))
    assert m["turnover"] == 0 and m["cost"] == 0
    assert m["model_ret"] == pytest.approx(0.5 * 0.10 + 0.3 * -0.10)


def test_overnight_on_holdings_then_intraday_on_targets_with_cost():
    # hold A 100% overnight (+10%), switch fully to B at the open, B +5% intraday, 10 bps per side
    m = model_day(px(A=1.0), px(B=1.0), skip=set(), prev_close=px(A=100, B=20), open_=px(A=110, B=20),
                  close=px(A=120, B=21), cost_bps=10)
    assert m["turnover"] == pytest.approx(2.0)          # sell 100% A, buy 100% B
    assert m["model_ret"] == pytest.approx(1.10 * (1 - 0.002) * 1.05 - 1)


def test_skip_names_keep_their_drifted_weight():
    # A is in the band: its target says 0.5 but it is not traded, so it keeps the drifted 0.55/1.05 weight
    h = px(A=0.5)
    m = model_day(h, px(A=0.5, B=0.4), skip={"A"}, prev_close=px(A=100, B=10), open_=px(A=110, B=10),
                  close=px(A=110, B=11))
    drift_a = 0.5 * 1.1 / 1.05
    assert m["turnover"] == pytest.approx(0.4)
    assert m["model_ret"] == pytest.approx(1.05 * (1 - 0.0004) * (1 + 0.4 * 0.1) - 1)
    assert drift_a > 0.5


def test_missing_price_counts_as_flat_and_is_reported():
    m = model_day(px(A=0.5, X=0.1), px(A=0.5, X=0.1), skip={"A", "X"}, prev_close=px(A=100), open_=px(A=100),
                  close=px(A=102))
    assert m["missing"] == ["X"] and m["model_ret"] == pytest.approx(0.5 * 0.02)


def test_snapshot_round_trip_and_track(tmp_path):
    save_snapshot("2026-11-18", px(A=0.6), px(A=0.3, IEF=0.6), skip=set(), equity=1000.0, out_dir=tmp_path)
    snaps = load_snapshots(tmp_path)
    assert list(snaps) == [pd.Timestamp("2026-11-18")] and snaps[pd.Timestamp("2026-11-18")]["equity"] == 1000.0
    days = pd.to_datetime(["2026-11-17", "2026-11-18", "2026-11-19"])
    ao = pd.DataFrame({"A": [100, 100, 100], "IEF": [90, 90, 90]}, index=days, dtype="float64")
    ac = pd.DataFrame({"A": [100, 100, 110], "IEF": [90, 90, 90]}, index=days, dtype="float64")
    actual = pd.Series([0.029], index=[pd.Timestamp("2026-11-19")])
    df = track(snaps, ao, ac, actual, cost_bps=10)
    assert len(df) == 1 and str(df.date[0]) == "2026-11-19"
    model = (1 - 0.9 * 0.001) * (1 + 0.3 * 0.10) - 1         # turnover |0.3-0.6| + 0.6 = 0.9
    assert df.model_ret[0] == pytest.approx(model)
    assert df.gap_bps[0] == pytest.approx((0.029 - model) * 1e4)
    assert df.stocks_target[0] == pytest.approx(0.3)
    s = summarize(df)
    assert s["days"] == 1 and s["tracking_error_ann"] is None


def test_snapshot_without_a_next_trading_day_is_skipped(tmp_path):
    save_snapshot("2026-11-19", px(A=1.0), px(A=1.0), skip=set(), equity=1.0, out_dir=tmp_path)
    days = pd.to_datetime(["2026-11-18", "2026-11-19"])
    f = pd.DataFrame({"A": [1.0, 1.0]}, index=days)
    assert track(load_snapshots(tmp_path), f, f, pd.Series(dtype="float64")).empty
