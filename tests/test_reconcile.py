import json

import numpy as np
import pandas as pd
import pytest

from src.reconcile import fills_frame, orders_from_log, slippage, summarize


class _O:
    def __init__(self, id, filled_qty, filled_avg_price, filled_at, status="filled"):
        self.id, self.filled_qty, self.filled_avg_price, self.filled_at, self.status = id, filled_qty, filled_avg_price, filled_at, status


def _log(tmp_path):
    p = tmp_path / "orders.log"
    lines = [
        {"date": "2026-11-06", "orders": [{"ticker": "AAA", "side": "buy", "notional": 1000.0, "id": "a1"},
                                           {"ticker": "DEAD", "side": "buy", "notional": 5.0, "id": None, "error": "x"}]},
        {"date": "2026-11-09", "orders": [{"ticker": "BBB", "side": "sell", "notional": 2000.0, "id": "b1", "tif": "opg", "qty": 20},
                                           {"ticker": "CCC", "side": "buy", "notional": 500.0, "id": "c1"}]},
    ]
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return p


def test_orders_from_log_skips_rejected_and_filters_days(tmp_path):
    p = _log(tmp_path)
    log = orders_from_log(p)
    assert list(log["id"]) == ["a1", "b1", "c1"] and list(log["tif"]) == ["day", "opg", "day"]
    assert list(orders_from_log(p, days=1)["id"]) == ["b1", "c1"]


def test_fills_and_slippage_signed_per_side(tmp_path):
    log = orders_from_log(_log(tmp_path))
    alp = [
        _O("a1", "10", "101.0", pd.Timestamp("2026-11-09 09:31", tz="America/New_York")),        # buy, open 100 -> +100 bps
        _O("b1", "20", "99.0", pd.Timestamp("2026-11-10 09:30", tz="America/New_York")),         # sell, open 100 -> +100 bps
        _O("c1", "0", None, None, status="canceled"),
    ]
    f = fills_frame(alp, log)
    assert len(f) == 3 and f.loc[f["id"] == "c1", "qty"].iloc[0] == 0
    assert f.loc[f["id"] == "a1", "fill_date"].iloc[0] == pd.Timestamp("2026-11-09")
    bars = pd.DataFrame({
        "date": pd.to_datetime(["2026-11-06", "2026-11-09", "2026-11-09", "2026-11-10"]),
        "ticker": ["AAA", "AAA", "BBB", "BBB"],
        "open": [95.0, 100.0, 50.0, 100.0], "close": [98.0, 102.0, 102.0, 101.0],
    })
    sl = slippage(f, bars)
    a, b = sl.set_index("id").loc["a1"], sl.set_index("id").loc["b1"]
    assert a["bps_open"] == pytest.approx(100.0) and a["bps_close"] == pytest.approx((101 / 98 - 1) * 1e4)
    assert b["bps_open"] == pytest.approx(100.0) and b["prev_close"] == 102.0
    s = summarize(sl)
    assert s["priced"] == 2 and s["orders"] == 2
    assert s["bps_open_weighted"] == pytest.approx(100.0) and s["excess_vs_model_bps"] == pytest.approx(90.0)
    assert s["share_filled_within_5min_of_open"] == 1.0


def test_summarize_handles_no_reference():
    sl = pd.DataFrame({"qty": [1.0], "value": [10.0], "bps_open": [np.nan], "bps_close": [np.nan],
                       "filled_at": [pd.Timestamp("2026-11-09 09:31")]})
    assert summarize(sl) == {"orders": 1, "priced": 0}
