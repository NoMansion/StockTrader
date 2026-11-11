"""Broker adapters. Both expose the same three calls:

    positions()           -> pd.Series ticker -> market value ($)
    equity()              -> float total account value
    submit_targets(w)     -> list of orders, where w is ticker -> target weight

PaperBroker keeps state in a JSON file for dry runs / tests.
AlpacaBroker talks to Alpaca paper (or live) via alpaca-py.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd


class PaperBroker:
    def __init__(self, path: str | Path = "data/paper_account.json", starting_cash: float = 100_000.0):
        self.path = Path(path)
        if self.path.exists():
            self.acct = json.loads(self.path.read_text())
        else:
            self.acct = {"cash": starting_cash, "positions": {}}  # ticker -> {"qty", "price"}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.acct, indent=2))

    def mark(self, prices: pd.Series):
        for t, p in self.acct["positions"].items():
            if t in prices.index:
                p["price"] = float(prices[t])
        self._save()

    def positions(self) -> pd.Series:
        return pd.Series({t: p["qty"] * p["price"] for t, p in self.acct["positions"].items()}, dtype=float)

    def equity(self) -> float:
        return float(self.acct["cash"] + self.positions().sum())

    def submit_targets(self, target_w: pd.Series, prices: pd.Series) -> list[dict]:
        eq = self.equity()
        cur = self.positions()
        orders = []
        for t in target_w.index.union(cur.index):
            tgt_val = eq * float(target_w.get(t, 0.0))
            cur_val = float(cur.get(t, 0.0))
            delta = tgt_val - cur_val
            price = float(prices.get(t, 0.0))
            if price <= 0 or abs(delta) < 1.0:
                continue
            qty = delta / price
            pos = self.acct["positions"].setdefault(t, {"qty": 0.0, "price": price})
            pos["qty"] += qty
            pos["price"] = price
            self.acct["cash"] -= delta
            if abs(pos["qty"]) < 1e-9:
                del self.acct["positions"][t]
            orders.append({"ticker": t, "side": "buy" if qty > 0 else "sell", "qty": round(abs(qty), 4), "notional": round(abs(delta), 2)})
        self._save()
        return orders


class AlpacaBroker:
    """Alpaca via alpaca-py.

    order_type "market": fractional notional market orders, DAY (fill at/after next open).
    order_type "opg":    whole-share market-on-open orders (the opening auction, which is what the
                         backtest's "fill at next open" assumes); the sub-share remainder of each
                         delta goes as a DAY notional order so targets are still reached.
    """

    ORDER_TYPES = ("market", "opg")

    def __init__(self, order_type: str = "market"):
        from alpaca.trading.client import TradingClient  # optional dependency

        key, sec = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
        if not (key and sec):
            raise RuntimeError("Set ALPACA_API_KEY / ALPACA_SECRET_KEY in .env")
        paper = os.environ.get("ALPACA_PAPER", "true").lower() == "true"
        self.client = TradingClient(key, sec, paper=paper)
        self.order_type = _check_order_type(order_type)

    def positions(self) -> pd.Series:
        return pd.Series({p.symbol: float(p.market_value) for p in self.client.get_all_positions()}, dtype=float)

    def position_qty(self) -> pd.Series:
        return pd.Series({p.symbol: float(p.qty) for p in self.client.get_all_positions()}, dtype=float)

    def equity(self) -> float:
        return float(self.client.get_account().equity)

    def _wait_for_cancels(self, timeout_s: float = 30.0, poll_s: float = 1.0) -> bool:
        """cancel_orders() returns before Alpaca has released the shares the old orders were holding. A
        close_position sent in that gap is rejected with 40310000 "insufficient qty available"
        (2026-11-11: two exits lost that way). Wait until no order is open, at most `timeout_s`."""
        get_orders = getattr(self.client, "get_orders", None)
        if get_orders is None:
            return True
        deadline = time.monotonic() + timeout_s
        while True:
            if not get_orders():                      # default filter: open orders only
                return True
            if time.monotonic() >= deadline:
                print(f"  warning: orders still open {timeout_s:.0f}s after cancelling; exits of those names may be rejected")
                return False
            time.sleep(poll_s)

    def submit_targets(self, target_w: pd.Series, prices: pd.Series | None = None) -> list[dict]:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        # stale unfilled orders from an earlier run would double up with today's deltas
        self.client.cancel_orders()
        self._wait_for_cancels()
        eq = self.equity()
        cur = self.positions()
        orders = []
        # sells first so cash is available for buys
        deltas = {t: eq * float(target_w.get(t, 0.0)) - float(cur.get(t, 0.0)) for t in target_w.index.union(cur.index)}
        opg = getattr(self, "order_type", "market") == "opg"
        held = self.position_qty() if opg else None
        for t, delta in sorted(deltas.items(), key=lambda kv: kv[1]):
            if abs(delta) < 1.0:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            reqs = []
            if opg:
                price = float(prices.get(t, 0.0)) if prices is not None else 0.0
                shares = int(abs(delta) // price) if price > 0 else 0
                if side == OrderSide.SELL:
                    shares = min(shares, int(float(held.get(t, 0.0))))      # never short via rounding
                if shares > 0:
                    reqs.append(MarketOrderRequest(symbol=t, qty=shares, side=side, time_in_force=TimeInForce.OPG))
                rest = round(abs(delta) - shares * price, 2) if price > 0 else round(abs(delta), 2)
                if rest >= 1.0:   # sub-share remainder (or no price): fractional notional at the open, DAY
                    reqs.append(MarketOrderRequest(symbol=t, notional=rest, side=side, time_in_force=TimeInForce.DAY))
            elif side == OrderSide.SELL and float(target_w.get(t, 0.0)) <= 0.0:
                # full exit: liquidate the whole position by quantity. A notional sell is converted to shares at
                # the broker's current price, which can exceed the shares held and gets rejected (40310000).
                try:
                    o = self.client.close_position(t)
                    orders.append({"ticker": t, "side": side.value, "tif": "day", "close": True,
                                   "notional": round(abs(delta), 2), "id": str(o.id)})
                except Exception as ex:
                    print(f"  close rejected for {t} (${abs(delta):,.0f}): {str(ex)[:160]}")
                    orders.append({"ticker": t, "side": side.value, "tif": "day", "close": True,
                                   "notional": round(abs(delta), 2), "id": None, "error": str(ex)[:200]})
                continue
            else:
                reqs.append(MarketOrderRequest(symbol=t, notional=round(abs(delta), 2), side=side, time_in_force=TimeInForce.DAY))
            for req in reqs:
                rec = {"ticker": t, "side": side.value, "tif": req.time_in_force.value}
                if req.qty is not None:
                    rec["qty"] = int(req.qty)
                    rec["notional"] = round(int(req.qty) * price, 2)
                else:
                    rec["notional"] = float(req.notional)
                try:
                    o = self.client.submit_order(req)
                except Exception as ex:  # one unknown/halted symbol must not abort the rest of the rebalance
                    print(f"  order rejected for {t} ({side.value} ${abs(delta):,.0f}): {str(ex)[:160]}")
                    orders.append({**rec, "id": None, "error": str(ex)[:200]})
                    continue
                orders.append({**rec, "id": str(o.id)})
        return orders


def _check_order_type(kind: str) -> str:
    if kind not in AlpacaBroker.ORDER_TYPES:
        raise ValueError(f"live.order_type must be one of {AlpacaBroker.ORDER_TYPES}, got {kind!r}")
    return kind


def make_broker(kind: str, order_type: str = "market"):
    return PaperBroker() if kind == "paper" else AlpacaBroker(order_type=order_type)
