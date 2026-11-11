import pandas as pd

from src.broker import AlpacaBroker


class _Order:
    def __init__(self, i):
        self.id = f"id{i}"


class _Account:
    equity = "100000"


class _StubClient:
    """Minimal stand-in for alpaca-py's TradingClient."""

    def __init__(self, positions, reject=()):
        self._pos = positions
        self._reject = set(reject)
        self.cancelled = 0
        self.submitted = []
        self.reqs = []

    def cancel_orders(self):
        self.cancelled += 1

    def get_account(self):
        return _Account()

    def get_all_positions(self):
        class P:
            def __init__(self, s, v):
                self.symbol, self.market_value, self.qty = s, str(v), str(v / 100.0)   # every stub position costs $100/share
        return [P(s, v) for s, v in self._pos.items()]

    def submit_order(self, req):
        if req.symbol in self._reject:
            raise RuntimeError(f'asset "{req.symbol}" not found')
        self.submitted.append((req.symbol, req.side.value, float(req.notional) if req.notional is not None else None))
        self.reqs.append(req)
        return _Order(len(self.submitted))

    def close_position(self, symbol):
        # full exits are liquidated by position (the real client converts a notional sell to shares at its
        # own price, which can exceed the shares held); recorded as a sell of the whole position value
        if symbol in self._reject:
            raise RuntimeError(f'asset "{symbol}" not found')
        self.submitted.append((symbol, "sell", float(self._pos[symbol])))
        return _Order(len(self.submitted))


def _broker(client, order_type="market"):
    b = AlpacaBroker.__new__(AlpacaBroker)
    b.client = client
    b.order_type = order_type
    return b


def test_submit_targets_cancels_stale_orders_sells_first_and_skips_rejections():
    client = _StubClient(positions={"OLD": 10_000.0, "KEEP": 5_000.0}, reject={"DEAD-202611"})
    target = pd.Series({"KEEP": 0.05, "NEW": 0.10, "DEAD-202611": 0.02, "TINY": 0.000005})
    orders = _broker(client).submit_targets(target)
    assert client.cancelled == 1
    assert client.submitted[0] == ("OLD", "sell", 10_000.0)             # sells go first
    assert ("NEW", "buy", 10_000.0) in client.submitted
    assert all(o[0] != "KEEP" for o in client.submitted)                 # already at target
    assert all(o[0] != "TINY" for o in client.submitted)                 # below the $1 floor
    rejected = [o for o in orders if o.get("error")]
    assert [o["ticker"] for o in rejected] == ["DEAD-202611"] and rejected[0]["id"] is None
    assert len([o for o in orders if o["id"]]) == 2


def test_submit_targets_waits_until_cancelled_orders_are_gone():
    class _Slow(_StubClient):
        """Old orders stay open for two polls after cancel_orders(), as on Alpaca."""
        polls = 0

        def get_orders(self):
            self.polls += 1
            assert self.cancelled == 1 and not self.submitted      # polled after the cancel, before any new order
            return ["old order"] if self.polls <= 2 else []

    client = _Slow(positions={"OLD": 10_000.0})
    b = _broker(client)
    b._wait_for_cancels = lambda: AlpacaBroker._wait_for_cancels(b, timeout_s=5.0, poll_s=0.01)
    orders = b.submit_targets(pd.Series({"NEW": 0.10}))
    assert client.polls == 3 and len(orders) == 2
    # a cancel that never settles gives up after the timeout and still submits
    stuck = _Slow(positions={})
    stuck.cancelled = 1
    stuck.get_orders = lambda: ["stuck"]
    assert AlpacaBroker._wait_for_cancels(_broker(stuck), timeout_s=0.05, poll_s=0.01) is False


def test_opg_orders_are_whole_shares_with_a_day_notional_remainder():
    import pytest

    from src.broker import _check_order_type

    client = _StubClient(positions={"OLD": 10_050.0, "TRIM": 5_000.0})            # OLD 100.5 sh, TRIM 50 sh
    target = pd.Series({"NEW": 0.10, "TRIM": 0.03, "ODD": 0.0005})                   # NEW $10k, TRIM $3k, ODD $50
    prices = pd.Series({"NEW": 300.0, "TRIM": 100.0, "OLD": 100.0, "ODD": 80.0})
    orders = _broker(client, "opg").submit_targets(target, prices)
    by = {}
    for r in client.reqs:
        by.setdefault(r.symbol, []).append((r.side.value, r.time_in_force.value, r.qty, r.notional))
    assert by["OLD"] == [("sell", "opg", 100, None), ("sell", "day", None, 50.0)]   # full exit: 100 sh + the half share
    assert by["TRIM"] == [("sell", "opg", 20, None)]                                 # $2,000 / $100 exactly
    assert by["NEW"] == [("buy", "opg", 33, None), ("buy", "day", None, 100.0)]     # 33 x $300 + $100 remainder
    assert by["ODD"] == [("buy", "day", None, 50.0)]                                 # below one share: notional only
    assert [o["ticker"] for o in orders][:3] == ["OLD", "OLD", "TRIM"]               # sells first
    assert all(o["tif"] in ("opg", "day") for o in orders) and all(o["id"] for o in orders)
    assert [o for o in orders if o["ticker"] == "NEW"][0]["notional"] == 9_900.0
    with pytest.raises(ValueError):
        _check_order_type("limit")
