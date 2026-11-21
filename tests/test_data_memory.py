"""The low-memory loading path (2026-11-21) must give exactly what the old path gave."""
import numpy as np
import pandas as pd
import pytest

from src.data import clean_bars, clean_wide, to_wide, to_wide_many, write_parquet_chunked

FIELDS = ["adj_close", "volume", "close"]


def _messy_bars(seed=0, n_days=60, tickers=("AAA", "BBB", "CCC", "DDD", "EEE")):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2024-01-02", periods=n_days)
    rows = []
    for t in tickers:
        for d in days:
            if rng.random() < 0.15:                     # gaps
                continue
            px = float(rng.uniform(5, 50))
            rows.append({"date": d, "ticker": t, "open": px, "high": px * 1.01, "low": px * 0.99,
                         "close": px, "volume": float(rng.integers(0, 10_000)), "adj_close": px * 0.9})
    df = pd.DataFrame(rows).sample(frac=1.0, random_state=seed).reset_index(drop=True)   # unsorted, like a fetch
    bad = df.sample(n=12, random_state=seed + 1).index
    df.loc[bad[:3], "close"] = 0.000001                  # Norgate placeholder
    df.loc[bad[3:6], "high"] = df.loc[bad[3:6], "low"] * 0.5   # high < low
    df.loc[bad[6:8], "adj_close"] = np.nan
    df.loc[bad[8:10], "close"] = df.loc[bad[8:10], "high"] * 1.5   # close above high
    dups = df.sample(n=15, random_state=seed + 2).copy()
    dups["close"] = dups["close"] * 1.001; dups["adj_close"] = dups["adj_close"] * 1.001
    dups["high"] = dups["high"] * 1.01
    return pd.concat([df, dups, dups.assign(close=dups["close"] * 1.0005)], ignore_index=True)   # triplicates too


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_clean_wide_matches_clean_bars_then_pivot(seed):
    raw = _messy_bars(seed)
    keep = ["AAA", "BBB", "DDD", "EEE"]                  # CCC is not requested: must be dropped
    old_bars = raw[raw["ticker"].isin(keep)].copy()
    old = {f: clean_bars(old_bars).pivot(index="date", columns="ticker", values=f).sort_index() for f in FIELDS}
    new = clean_wide(raw, FIELDS, tickers=keep)
    for f in FIELDS:
        pd.testing.assert_frame_equal(new[f], old[f], check_exact=True)
        assert new[f].index.equals(old[f].index) and new[f].columns.equals(old[f].columns)
    assert "CCC" not in new["close"].columns


def test_to_wide_matches_pivot():
    b = clean_bars(_messy_bars(3))
    for f in FIELDS:
        pd.testing.assert_frame_equal(to_wide(b, f), b.pivot(index="date", columns="ticker", values=f).sort_index(),
                                      check_exact=True)
    many = to_wide_many(b, FIELDS)
    assert set(many) == set(FIELDS)


def test_clean_bars_without_copy_matches_copy():
    raw = _messy_bars(4)
    a = clean_bars(raw.copy())
    b = clean_bars(raw.copy(), copy=False)
    pd.testing.assert_frame_equal(a, b, check_exact=True)


def test_chunked_parquet_round_trip(tmp_path):
    df = _messy_bars(5)
    df["assetid"] = np.arange(len(df), dtype="int64")
    p1, p2 = tmp_path / "a.parquet", tmp_path / "b.parquet"
    df.to_parquet(p1, index=False)
    write_parquet_chunked(df, p2, rows_per_chunk=37)
    pd.testing.assert_frame_equal(pd.read_parquet(p2), pd.read_parquet(p1), check_exact=True)
    assert not (tmp_path / "b.parquet.tmp").exists()


def test_chunked_parquet_empty_frame(tmp_path):
    df = pd.DataFrame({c: pd.Series(dtype="float64") for c in ["open", "close"]})
    write_parquet_chunked(df, tmp_path / "e.parquet")
    assert len(pd.read_parquet(tmp_path / "e.parquet")) == 0
