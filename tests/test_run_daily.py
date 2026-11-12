import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_daily  # noqa: E402


def test_trading_days_since_counts_bars_on_the_price_calendar():
    idx = pd.bdate_range("2026-11-02", periods=8)
    # no new bar since the last rebalance: 0, so even a daily cadence (every = 1) holds instead of re-trading
    assert run_daily.trading_days_since(idx, idx[5], idx[5]) == 0
    assert run_daily.trading_days_since(idx, idx[5], idx[6]) == 1
    assert run_daily.trading_days_since(idx, idx[4], idx[7]) == 3      # spans a weekend
    # a rebalance date that is not on the calendar never blocks a rebalance
    assert run_daily.trading_days_since(idx, pd.Timestamp("2026-11-07"), idx[7]) >= 10 ** 6


def _panels(n_days=700, n_names=6, seed=0):
    import numpy as np
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    cols = [f"T{i}" for i in range(n_names)]
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, (n_days, n_names)), axis=0)), index=idx, columns=cols)
    volume = pd.DataFrame(rng.uniform(1e5, 1e6, (n_days, n_names)), index=idx, columns=cols)
    # fundamentals on their own sparse (filing) calendar, one name never reported: the window must not lose the
    # value filed before it starts
    fdays = idx[::63]
    fund = {"sue": pd.DataFrame(rng.normal(0, 1, (len(fdays), n_names - 1)), index=fdays, columns=cols[:-1]),
            "fcf_yield": pd.DataFrame(rng.normal(0, 1, (len(fdays), n_names - 1)), index=fdays, columns=cols[:-1])}
    for p in fund.values():
        p.loc[p.index > idx[300], "T1"] = float("nan")    # T1's last filing is before a 300-bar window starts
    return close, volume, fund


def test_live_features_window_matches_whole_history_on_today():
    from src.config import build_rules, load_config
    from src.features import compute_features
    close, volume, fund = _panels()
    cfg = load_config()
    cfg["portfolio"].pop("books", None)
    cfg["model"]["type"] = "sue_fcfy"
    cfg["live"] = {**(cfg.get("live") or {}), "feature_window_days": 300}
    rules = build_rules(cfg)
    today = close.index[-1]
    win = run_daily.live_features(cfg, rules, close, volume, close, fund)
    full = compute_features(close, volume, raw_close=close, fundamentals=fund)
    assert win.index.get_level_values("date").min() == close.index[-300]
    a, b = full.xs(today, level="date"), win.xs(today, level="date")
    pd.testing.assert_frame_equal(a[sorted(a.columns)], b[sorted(a.columns)], check_exact=False, rtol=1e-12, atol=1e-12)
    cfg["live"]["feature_window_days"] = 0            # 0 = whole history
    assert len(run_daily.live_features(cfg, rules, close, volume, close, fund)) == len(full)
