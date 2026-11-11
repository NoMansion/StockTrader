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
