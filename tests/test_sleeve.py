import numpy as np
import pandas as pd
import pytest

from src import exposure
from src.backtest import BacktestResult
from src.sleeve import (SleeveConfig, apply_cash_yield, apply_sleeve, live_sleeve_targets, sleeve_allocation,
                        sleeve_prices)

IDX = pd.bdate_range("2003-01-02", periods=600)


def _fake_loader(symbols):
    """ETF appears half way through; the fallback index exists throughout; T-bill at 4%."""
    out = {}
    for s in symbols:
        if s == "%IRX":
            out[s] = pd.Series(4.0, index=IDX)
            continue
        rng = np.random.default_rng(sum(map(ord, s)))      # deterministic per symbol, whatever the call order
        px = pd.Series(np.exp(rng.normal(0.0003, 0.006, len(IDX)).cumsum()) * 100, index=IDX)
        if s in ("IEF", "GLD", "TLT"):
            px.iloc[:300] = np.nan          # ETF did not exist yet
        out[s] = px
    return pd.DataFrame(out)


@pytest.fixture(autouse=True)
def _stub_loader(monkeypatch):
    monkeypatch.setattr(exposure, "EXT_LOADER", _fake_loader)


def _result(invested: float, n_days=600):
    daily = pd.DataFrame({"ret": 0.0, "bench_ret": 0.0, "turnover": 0.0, "cost": 0.0, "n_pos": 3, "ic": np.nan}, index=IDX[:n_days])
    w = pd.DataFrame(invested / 3, index=daily.index, columns=["A", "B", "C"])
    return BacktestResult(daily=daily, weights=w, trades=pd.DataFrame())


def test_splice_uses_fallback_before_etf_exists_and_etf_after():
    px = sleeve_prices(("IEF", "GLD"), IDX)
    raw = _fake_loader(["IEF", "$USBIG", "GLD", "$BCOMPR"])
    early = px["IEF"].pct_change().iloc[10:300]
    assert np.allclose(early.values, raw["$USBIG"].pct_change().iloc[10:300].values)
    late = px["IEF"].pct_change().iloc[310:]
    assert np.allclose(late.values, raw["IEF"].pct_change().iloc[310:].values)
    assert px.notna().all().all() and (px > 0).all().all()


def test_allocations_sum_to_one_or_zero():
    px = sleeve_prices(("IEF", "GLD"), IDX)
    eq = sleeve_allocation(px, "always_eq")
    assert np.allclose(eq.sum(axis=1), 1.0) and np.allclose(eq["IEF"], 0.5)
    tr = sleeve_allocation(px, "trend_eq")
    assert set(np.round(tr.sum(axis=1).unique(), 6)) <= {0.0, 1.0}
    with pytest.raises(ValueError):
        sleeve_allocation(px, "bogus")


def test_apply_sleeve_invests_idle_cash_above_buffer_with_one_day_lag():
    res = _result(invested=0.33)
    cfg = SleeveConfig(assets=("IEF", "GLD"), cost_bps=0.0)
    px = sleeve_prices(cfg.assets, IDX)
    out = apply_sleeve(res, base_cash_buffer=0.02, cfg=cfg, prices=px)
    assert out.daily["sleeve_w"].iloc[1:].round(6).eq(round(1 - 0.33 - 0.02, 6)).all()
    expected = 0.65 * 0.5 * (px["IEF"].pct_change() + px["GLD"].pct_change())
    assert np.allclose(out.daily["sleeve_ret"].iloc[2:], expected.iloc[2:])
    assert np.allclose(out.daily["ret"], out.daily["sleeve_ret"])    # stock ret was zero


def test_sleeve_frac_and_cost_reduce_the_sleeve():
    full = apply_sleeve(_result(0.33), 0.02, SleeveConfig(cost_bps=0.0), sleeve_prices(("IEF", "GLD"), IDX))
    half = apply_sleeve(_result(0.33), 0.02, SleeveConfig(frac=0.5, cost_bps=0.0), sleeve_prices(("IEF", "GLD"), IDX))
    assert np.allclose(half.daily["sleeve_ret"], full.daily["sleeve_ret"] / 2)
    costly = apply_sleeve(_result(0.33), 0.02, SleeveConfig(cost_bps=50.0), sleeve_prices(("IEF", "GLD"), IDX))
    assert costly.daily["sleeve_ret"].iloc[0] < full.daily["sleeve_ret"].iloc[0]   # entry cost charged on day 0
    assert np.allclose(costly.daily["sleeve_ret"].iloc[1:], full.daily["sleeve_ret"].iloc[1:])  # then no trades


def test_fully_invested_book_gets_no_sleeve():
    out = apply_sleeve(_result(0.98), 0.02, SleeveConfig(), sleeve_prices(("IEF", "GLD"), IDX))
    assert out.daily["sleeve_w"].abs().max() < 1e-9


def test_cash_yield_accrues_on_cash_not_in_stocks_or_sleeve():
    res = apply_sleeve(_result(0.33), 0.02, SleeveConfig(frac=0.5, cost_bps=0.0), sleeve_prices(("IEF", "GLD"), IDX))
    out = apply_cash_yield(res)
    # idle = 1 - 0.33 - 0.325 (half sleeve) = 0.345 of equity at 4%/yr
    assert out.daily["cash_ret"].iloc[5] == pytest.approx(0.345 * 0.04 / 252, rel=1e-6)


def test_live_targets_split_idle_cash_equally():
    cfg = SleeveConfig(assets=("IEF", "GLD"))
    px = sleeve_prices(cfg.assets, IDX)
    stocks = pd.Series({"AAPL": 0.2, "MSFT": 0.13})
    w = live_sleeve_targets(stocks, base_cash_buffer=0.02, cfg=cfg, prices=px)
    assert w["IEF"] == pytest.approx(0.325) and w["GLD"] == pytest.approx(0.325)
    assert live_sleeve_targets(pd.Series({"AAPL": 0.98}), 0.02, cfg, px).sum() == 0.0


def test_unknown_asset_is_rejected():
    with pytest.raises(ValueError):
        SleeveConfig(assets=("IEF", "XYZ"))


def test_full_sleeve_takes_everything_above_its_base_buffer():
    """full: true turns a large cash_buffer into a stock/sleeve split instead of a T-bill pile."""
    cfg = SleeveConfig(assets=("SPY", "IEF", "GLD"), full=True, base=0.02, cost_bps=0.0)
    px = sleeve_prices(cfg.assets, IDX)
    out = apply_sleeve(_result(0.24), base_cash_buffer=0.67, cfg=cfg, prices=px)
    assert out.daily["sleeve_w"].iloc[1:].round(6).eq(round(1 - 0.24 - 0.02, 6)).all()
    plain = apply_sleeve(_result(0.24), 0.67, SleeveConfig(assets=("SPY", "IEF", "GLD"), cost_bps=0.0), px)
    assert plain.daily["sleeve_w"].iloc[1:].round(6).eq(round(1 - 0.24 - 0.67, 6)).all()
    live = live_sleeve_targets(pd.Series({"AAPL": 0.24}), 0.67, cfg, px)
    assert live.sum() == pytest.approx(0.74, abs=1e-5) and live["SPY"] == pytest.approx(0.74 / 3, abs=1e-5)
