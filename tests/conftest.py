import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def synthetic_prices():
    """600 trading days x 30 tickers of geometric random walks with a few
    persistent 'trend' names so a momentum ranker has something to find."""
    rng = np.random.default_rng(0)
    n_days, n_tk = 600, 30
    tickers = [f"T{i:02d}" for i in range(n_tk)]
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    drift = np.zeros(n_tk)
    drift[:5] = 0.0012   # trending winners
    drift[-5:] = -0.0008 # trending losers
    rets = rng.normal(drift, 0.015, size=(n_days, n_tk))
    close = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=tickers)
    volume = pd.DataFrame(rng.integers(1e5, 1e6, size=(n_days, n_tk)), index=dates, columns=tickers)
    return close, volume
