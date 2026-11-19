import json

from src.open_fallback import last_batch, plan_resends


def o(t, side, tif, qty, oid):
    return {"ticker": t, "side": side, "tif": tif, "qty": qty, "id": oid}


def st(status, qty, filled=0):
    return {"status": status, "qty": qty, "filled_qty": filled}


def test_expired_auction_orders_are_resent_sells_first():
    batch = [o("AAA", "buy", "opg", 10, "1"), o("BBB", "sell", "opg", 5, "2"), o("CCC", "buy", "day", 0.4, "3")]
    plan, notes = plan_resends(batch, {"1": st("expired", 10), "2": st("expired", 5)}, {"BBB": 5.6})
    assert [(r["ticker"], r["side"], r["qty"]) for r in plan] == [("BBB", "sell", 5), ("AAA", "buy", 10)]
    assert notes == []


def test_filled_and_day_orders_are_left_alone():
    batch = [o("AAA", "buy", "opg", 10, "1"), o("DDD", "buy", "day", 3, "4")]
    plan, _ = plan_resends(batch, {"1": st("filled", 10, 10), "4": st("expired", 3)}, {})
    assert plan == []


def test_partial_fill_resends_only_the_rest():
    plan, _ = plan_resends([o("AAA", "buy", "opg", 10, "1")], {"1": st("canceled", 10, 7)}, {})
    assert plan[0]["qty"] == 3


def test_sell_is_capped_at_shares_held_never_short():
    plan, _ = plan_resends([o("BBB", "sell", "opg", 8, "2"), o("EEE", "sell", "opg", 4, "5")],
                           {"2": st("expired", 8), "5": st("expired", 4)}, {"BBB": 6.0})
    assert [(r["ticker"], r["qty"]) for r in plan] == [("BBB", 6)]       # EEE no longer held: nothing to sell


def test_each_order_is_resent_once():
    batch = [o("AAA", "buy", "opg", 10, "1")]
    plan, _ = plan_resends(batch, {"1": st("expired", 10)}, {}, already={"1"})
    assert plan == []


def test_still_open_unknown_and_never_accepted_orders_are_noted_not_sent():
    batch = [o("AAA", "buy", "opg", 10, "1"), o("BBB", "buy", "opg", 2, "9"),
             {"ticker": "ZZZ", "side": "buy", "tif": "opg", "qty": 1, "id": None, "error": "asset not tradable"}]
    plan, notes = plan_resends(batch, {"1": st("accepted", 10)}, {})
    assert plan == [] and len(notes) == 3


def test_last_batch_skips_fallback_lines(tmp_path):
    p = tmp_path / "orders.log"
    p.write_text(json.dumps({"date": "2026-11-18", "orders": [o("AAA", "buy", "opg", 1, "1")]}) + "\n"
                 + json.dumps({"date": "2026-11-19", "fallback": True, "orders": []}) + "\n")
    assert last_batch(p)["date"] == "2026-11-18"
