import json

import pandas as pd

from src.monitor import (
    append_equity, equity_stats, health_checks, load_equity, load_orders, load_ranking, write_ranking,
)


def test_equity_log_is_idempotent_per_day(tmp_path):
    append_equity("2026-01-02", 100_000, 10_000, 5, data_dir=tmp_path)
    append_equity("2026-01-02", 100_500, 9_000, 5, data_dir=tmp_path)   # rerun same day
    append_equity("2026-01-05", 101_000, 8_000, 6, data_dir=tmp_path)
    eq = load_equity(tmp_path)
    assert len(eq) == 2
    assert eq["equity"].iloc[0] == 100_500
    assert eq["drawdown"].iloc[-1] == 0


def test_ranking_actions(tmp_path):
    scores = pd.Series({"A": 3.0, "B": 2.0, "C": 1.0, "D": 0.5})
    prev = pd.Series({"A": 0.4, "B": 0.3, "D": 0.2})
    new = pd.Series({"A": 0.45, "B": 0.25, "C": 0.2})
    write_ranking(scores, new, prev, top_n=3, data_dir=tmp_path)
    r = load_ranking(tmp_path).set_index("ticker")
    assert r.loc["A", "action"] == "ADD"
    assert r.loc["B", "action"] == "TRIM"
    assert r.loc["C", "action"] == "ENTER"
    assert r.loc["D", "action"] == "EXIT"
    assert list(r["rank"]) == [1, 2, 3, 4]
    assert r["in_ranking"].sum() == 3


def test_orders_log_reader(tmp_path):
    (tmp_path / "orders.log").write_text(
        json.dumps({"date": "2026-01-02", "orders": [{"ticker": "A", "side": "buy", "notional": 100}]}) + "\n"
        + "garbage line\n"
        + json.dumps({"date": "2026-01-05", "orders": []}) + "\n"
    )
    o = load_orders(tmp_path)
    assert len(o) == 1 and o["ticker"].iloc[0] == "A"


def test_health_checks_flag_stale_and_drawdown():
    idx = pd.to_datetime(["2026-01-02", "2026-01-05"])
    eq = pd.DataFrame({"equity": [100.0, 88.0], "cash": [0, 0], "n_positions": [5, 5]}, index=idx)
    eq["drawdown"] = eq["equity"] / eq["equity"].cummax() - 1
    msgs = health_checks(eq, pd.DataFrame(), today="2026-01-20")
    levels = [l for l, _ in msgs]
    assert levels.count("error") == 2  # stale + >10% drawdown


def test_equity_stats_basic():
    eq = pd.Series([100, 101, 102, 101, 103], index=pd.bdate_range("2026-01-01", periods=5))
    s = equity_stats(eq)
    assert abs(s["total_return"] - 0.03) < 1e-12
    assert s["max_dd"] < 0
    assert s["days"] == 5
