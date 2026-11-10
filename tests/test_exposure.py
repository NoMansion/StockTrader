import numpy as np
import pandas as pd
import pytest

from src.exposure import exposure_series, scale_rules, universe_index
from src.portfolio import Rules


def _panel(n_days=700, n=8, drift=0.0, vol=0.01, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=n_days)
    cols = [f"T{i}" for i in range(n)]
    close = pd.DataFrame(np.exp(rng.normal(drift, vol, (n_days, n)).cumsum(0)) * 50, index=idx, columns=cols)
    return close


def test_universe_index_uses_only_members():
    close = _panel()
    members = pd.DataFrame(True, index=close.index, columns=close.columns)
    members["T0"] = False
    full = universe_index(close, None)
    part = universe_index(close, members)
    assert len(full) == len(close) and not np.allclose(full.values, part.values)


def test_vol_target_is_capped_at_one_and_falls_when_vol_rises():
    close = _panel(vol=0.002)                               # very calm -> capped at 1
    assert (exposure_series("vt15", close, None) <= 1.0 + 1e-12).all()
    assert exposure_series("vt15", close, None).iloc[-1] == pytest.approx(1.0)
    wild = _panel(n=1, vol=0.03)                            # one name, ~48% annualized -> well below 1
    assert exposure_series("vt15", wild, None).iloc[-1] < 0.5


def test_binary_and_half_kinds_take_expected_values():
    close = _panel()
    assert set(exposure_series("ret12m", close, None).dropna().unique()) <= {0.0, 1.0}
    assert set(exposure_series("ret12m_half", close, None).dropna().unique()) <= {0.5, 1.0}
    assert set(exposure_series("ma200_half", close, None).dropna().unique()) <= {0.5, 1.0}
    assert set(exposure_series("ret12m_ma200", close, None).dropna().unique()) <= {0.0, 0.5, 1.0}
    with pytest.raises(ValueError):
        exposure_series("nope", close, None)


def test_scale_rules_shrinks_budget():
    r = Rules(cash_buffer=0.02)
    assert scale_rules(r, 1.0).cash_buffer == pytest.approx(0.02)
    assert scale_rules(r, 0.5).cash_buffer == pytest.approx(0.51)
    assert scale_rules(r, 0.0).cash_buffer == pytest.approx(1.0)
    assert scale_rules(r, 1.7).cash_buffer == pytest.approx(0.02)   # clipped


def test_dict_spec_matches_named_kinds():
    close = _panel(n_days=900, vol=0.012)
    for name, spec in [("ret12mhalf_vt15", {"vt": 15, "ret_days": 252, "ret_low": 0.5}),
                       ("vt15", {"vt": 15}), ("ret12m_half", {"ret_days": 252}),
                       ("ma200_half", {"ma": 200, "ma_low": 0.5})]:
        a, b = exposure_series(name, close, None), exposure_series(spec, close, None)
        assert np.allclose(a.values, b.values), name
    e = exposure_series({"vt": 15, "floor": 0.3, "ema": 5}, close, None)
    assert (e >= 0.3 - 1e-12).all() and (e <= 1.0 + 1e-12).all()
    dd = exposure_series("dd10half_vt15", close, None)
    assert (dd <= exposure_series("vt15", close, None) + 1e-12).all()


def _fake_breadth(close, neg_from=None):
    """Stub loader: highs-lows positive everywhere except from `neg_from` on; A/D line rising."""
    idx = close.index
    hi = pd.Series(100.0, index=idx); lo = pd.Series(50.0, index=idx)
    if neg_from is not None:
        lo.loc[neg_from:] = 300.0
    ad = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    return lambda symbols: pd.DataFrame({"#NYSEHI": hi, "#NYSELO": lo, "#NYSEAD": ad})[symbols]


def test_highs_lows_gate_halves_exposure_when_breadth_turns_negative(monkeypatch):
    import src.exposure as ex
    close = _panel(vol=0.002)
    cut = close.index[-100]
    monkeypatch.setattr(ex, "EXT_LOADER", _fake_breadth(close, neg_from=cut))
    e = exposure_series({"hl_days": 10}, close, None)
    assert e.loc[:cut].iloc[-11:-1].eq(1.0).all()             # positive breadth -> fully invested
    assert e.loc[cut:].iloc[10:].eq(0.5).all()                # 10 days after the turn the sum is negative
    e_low = exposure_series({"hl_days": 10, "hl_low": 0.2}, close, None)
    assert e_low.iloc[-1] == pytest.approx(0.2)


def test_gates_compose_with_vol_target_and_ad_gate_is_one_when_line_rises(monkeypatch):
    import src.exposure as ex
    close = _panel(vol=0.002)
    monkeypatch.setattr(ex, "EXT_LOADER", _fake_breadth(close))
    base = exposure_series({"vt": 15, "ret_days": 252, "ret_low": 0.5}, close, None)
    gated = exposure_series({"vt": 15, "ret_days": 252, "ret_low": 0.5, "hl_days": 10, "ad_ma": 100}, close, None)
    assert np.allclose(base.values, gated.values)              # both gates are 1.0 with healthy breadth
    monkeypatch.setattr(ex, "EXT_LOADER", _fake_breadth(close, neg_from=close.index[-50]))
    gated = exposure_series({"vt": 15, "ret_days": 252, "ret_low": 0.5, "hl_days": 10}, close, None)
    assert gated.iloc[-1] == pytest.approx(0.5 * base.iloc[-1])


def test_gate_loader_is_not_called_without_gate_keys(monkeypatch):
    import src.exposure as ex
    monkeypatch.setattr(ex, "EXT_LOADER", lambda symbols: (_ for _ in ()).throw(AssertionError("loader called")))
    close = _panel(vol=0.002)
    exposure_series({"vt": 15, "ret_days": 252, "ret_low": 0.5}, close, None)
    exposure_series("ret12mhalf_vt15", close, None)
