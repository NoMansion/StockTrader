"""Order execution. Only the paper broker exists; the live broker is deliberately a stub (see LiveBroker).

Two ways to enter, both simulated pessimistically:

  passive  a resting limit buy below the ask (what the research says winning accounts do: makers pay no fee and
           earn the spread; takers pay both). The paper order fills ONLY when, at a later cycle, the best ask has
           come down to our price, i.e. the market traded through us. That counts only the fills we would get
           when the price moves against us (adverse selection) and none of the lucky ones in between, so paper
           results should be worse than real ones, not better. Unfilled orders expire.
  taker    lift the ask now, walking displayed depth with a haircut, paying the taker fee.

Exits are always taker sells into the bid.
"""
from __future__ import annotations

import time

from .book import Book, simulate_buy, simulate_sell, summarize
from .fees import FeeModel
from .ledger import Ledger


class PaperBroker:
    mode = "paper"

    def __init__(self, ledger: Ledger, fees: FeeModel, depth_haircut: float = 0.5, resting_ttl_hours: float = 24.0):
        self.ledger, self.fees = ledger, fees
        self.depth_haircut = float(depth_haircut)
        self.resting_ttl_s = float(resting_ttl_hours) * 3600.0

    # ---- entries -------------------------------------------------------------
    def buy_taker(self, run_id: str, market_id: str, outcome: str, book: Book, usd: float, limit: float,
                  category: str | None = None, decision_id: int | None = None, now: float | None = None) -> float:
        """Returns dollars spent (0 if nothing was available under the limit)."""
        now = now or time.time()
        fills = simulate_buy(book, usd, limit, self.fees.fn(category), self.depth_haircut)
        shares, avg, fee = summarize(fills)
        oid = self.ledger.add_order({"ts": now, "run_id": run_id, "mode": self.mode, "market_id": market_id,
                                     "token_id": book.token_id, "outcome": outcome, "side": "BUY", "limit_price": limit,
                                     "usd": round(shares * avg + fee, 4), "shares": shares, "decision_id": decision_id,
                                     "status": "filled" if shares > 0 else "unfilled", "note": "taker"})
        for f in fills:
            self.ledger.apply_fill(oid, market_id, book.token_id, outcome, "BUY", f.price, f.shares, f.fee, ts=now)
        return shares * avg + fee

    def place_resting(self, run_id: str, market_id: str, outcome: str, token_id: str, price: float, usd: float,
                      decision_id: int | None = None, now: float | None = None) -> int:
        """A resting limit buy of usd/price shares at `price`. No cash moves until it fills; the open amount is
        counted as exposure by the trader so two cycles cannot spend the same dollars."""
        shares = int(usd / price * 100) / 100.0
        return self.ledger.add_order({"ts": now or time.time(), "run_id": run_id, "mode": self.mode, "market_id": market_id,
                                      "token_id": token_id, "outcome": outcome, "side": "BUY", "limit_price": price,
                                      "usd": round(shares * price, 4), "shares": shares, "decision_id": decision_id,
                                      "status": "resting", "note": "passive"})

    def resting(self, market_id: str | None = None):
        if market_id is None:
            return self.ledger.q("SELECT * FROM orders WHERE status='resting' AND mode=? ORDER BY ts", (self.mode,))
        return self.ledger.q("SELECT * FROM orders WHERE status='resting' AND mode=? AND market_id=?", (self.mode, market_id))

    def cancel(self, order_id: int, why: str) -> None:
        self.ledger.set_order_status(order_id, "cancelled", why)

    def work_resting(self, books: dict[str, Book], category_of=None, now: float | None = None) -> list[str]:
        """Fill, expire or keep every resting order. `books` maps token_id -> current Book."""
        now = now or time.time()
        log = []
        for o in self.resting():
            book = books.get(o["token_id"])
            price, shares = float(o["limit_price"]), float(o["shares"])
            if book is not None and book.best_ask is not None and book.best_ask <= price + 1e-9:
                cost = price * shares
                if cost > self.ledger.cash() + 1e-6:
                    self.cancel(o["id"], "not enough cash when the price came to it")
                    log.append(f"{o['market_id']}: resting {o['outcome']} order cancelled (cash)")
                    continue
                cat = category_of(o["market_id"]) if category_of else None
                fee = self.fees.per_share(price, cat, maker=True) * shares
                self.ledger.apply_fill(o["id"], o["market_id"], o["token_id"], o["outcome"], "BUY", price, shares, fee, ts=now)
                self.ledger.set_order_status(o["id"], "filled", f"ask came down to {book.best_ask:.3f}")
                log.append(f"{o['market_id']}: resting buy {o['outcome']} filled, {shares:g} @ {price:.3f}")
            elif now - float(o["ts"]) > self.resting_ttl_s:
                self.ledger.set_order_status(o["id"], "expired", "not filled within its time limit")
                log.append(f"{o['market_id']}: resting {o['outcome']} order expired unfilled")
        return log

    # ---- exits ----------------------------------------------------------------
    def sell_taker(self, run_id: str, market_id: str, outcome: str, book: Book, shares: float, limit: float,
                   category: str | None = None, decision_id: int | None = None, now: float | None = None) -> float:
        """Returns shares sold."""
        now = now or time.time()
        fills = simulate_sell(book, shares, limit, self.fees.fn(category), self.depth_haircut)
        sold, avg, fee = summarize(fills)
        oid = self.ledger.add_order({"ts": now, "run_id": run_id, "mode": self.mode, "market_id": market_id,
                                     "token_id": book.token_id, "outcome": outcome, "side": "SELL", "limit_price": limit,
                                     "usd": round(sold * avg - fee, 4), "shares": sold, "decision_id": decision_id,
                                     "status": "filled" if sold > 0 else "unfilled", "note": "taker exit"})
        for f in fills:
            self.ledger.apply_fill(oid, market_id, book.token_id, outcome, "SELL", f.price, f.shares, f.fee, ts=now)
        return sold


class LiveBroker:
    """Not built, on purpose. Real orders need facts that can only be confirmed against the venue with a funded,
    verified account, and none of them could be checked while this was written:

      - how a short (NO) order's price is expressed (the NO price, or the YES price it mirrors);
      - tick size and minimum order size per market;
      - what the settlement endpoint returns before a market has settled;
      - the fee actually charged, from orders.preview, against fees.py;
      - post-only behaviour (`participateDontInitiate`) and what a rejected post-only order looks like.

    docs/GO_LIVE.md lists the checks. Until they pass on the paper record AND on the venue, this class refuses."""

    mode = "live"

    def __init__(self, *a, **kw):
        raise NotImplementedError("live trading is not implemented: see docs/GO_LIVE.md")
