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
    """Alpaca via alpaca-py. Fractional notional orders, market, day."""

    def __init__(self):
        from alpaca.trading.client import TradingClient  # optional dependency

        key, sec = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
        if not (key and sec):
            raise RuntimeError("Set ALPACA_API_KEY / ALPACA_SECRET_KEY in .env")
        paper = os.environ.get("ALPACA_PAPER", "true").lower() == "true"
        self.client = TradingClient(key, sec, paper=paper)

    def positions(self) -> pd.Series:
        return pd.Series({p.symbol: float(p.market_value) for p in self.client.get_all_positions()}, dtype=float)

    def equity(self) -> float:
        return float(self.client.get_account().equity)

    def submit_targets(self, target_w: pd.Series, prices: pd.Series | None = None) -> list[dict]:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        eq = self.equity()
        cur = self.positions()
        orders = []
        # sells first so cash is available for buys
        deltas = {t: eq * float(target_w.get(t, 0.0)) - float(cur.get(t, 0.0)) for t in target_w.index.union(cur.index)}
        for t, delta in sorted(deltas.items(), key=lambda kv: kv[1]):
            if abs(delta) < 1.0:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            req = MarketOrderRequest(symbol=t, notional=round(abs(delta), 2), side=side, time_in_force=TimeInForce.DAY)
            o = self.client.submit_order(req)
            orders.append({"ticker": t, "side": side.value, "notional": round(abs(delta), 2), "id": str(o.id)})
        return orders


def make_broker(kind: str):
    return PaperBroker() if kind == "paper" else AlpacaBroker()
