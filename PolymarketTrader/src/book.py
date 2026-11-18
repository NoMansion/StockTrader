"""Order book snapshot and a conservative fill simulator. No network here.

The paper account only ever fills as a taker against displayed size: a buy lifts asks up to its limit price, a sell
hits bids down to its limit. It never assumes a resting order would have been filled at the mid, which is the
usual way paper results in thin markets come out better than real ones.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Book:
    token_id: str
    bids: list[tuple[float, float]] = field(default_factory=list)   # (price, shares), best (highest) first
    asks: list[tuple[float, float]] = field(default_factory=list)   # (price, shares), best (lowest) first
    ts: float = 0.0                                                 # epoch seconds of the snapshot
    tick: float = 0.01
    min_size: float = 0.0                                           # venue minimum order, in shares

    @classmethod
    def from_levels(cls, token_id: str, bids, asks, ts: float = 0.0, tick: float = 0.01, min_size: float = 0.0) -> "Book":
        """Build from raw levels in any order: each level a (price, size) pair or a {"price", "size"} dict."""
        def norm(levels):
            out = []
            for lv in levels or []:
                p, s = (lv["price"], lv["size"]) if isinstance(lv, dict) else lv
                p, s = float(p), float(s)
                if 0.0 < p < 1.0 and s > 0:
                    out.append((p, s))
            return out
        return cls(token_id, sorted(norm(bids), key=lambda x: -x[0]), sorted(norm(asks), key=lambda x: x[0]),
                   ts=ts, tick=tick, min_size=min_size)

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.bids and self.asks:
            return (self.bids[0][0] + self.asks[0][0]) / 2.0
        return None

    @property
    def spread(self) -> float | None:
        if self.bids and self.asks:
            return self.asks[0][0] - self.bids[0][0]
        return None

    def depth_usd(self, side: str, limit: float) -> float:
        """Dollars available on the asks at or below `limit` (side="buy") or on the bids at or above it ("sell")."""
        if side == "buy":
            return sum(p * s for p, s in self.asks if p <= limit + 1e-9)
        return sum(p * s for p, s in self.bids if p >= limit - 1e-9)


@dataclass
class Fill:
    price: float
    shares: float
    fee: float = 0.0


def simulate_buy(book: Book, usd: float, limit: float, fee_per_share=None, depth_haircut: float = 0.5) -> list[Fill]:
    """Spend up to `usd` (fees included) lifting asks priced at or below `limit`.

    depth_haircut: fraction of each displayed level assumed to be really there for us (0.5 = half). Displayed size
    in thin books is partly stale or pulled as soon as it is touched.
    fee_per_share: callable price -> fee in dollars per share, or None for no fee.
    """
    fills: list[Fill] = []
    left = float(usd)
    for price, size in book.asks:
        if price > limit + 1e-9 or left <= 1e-9:
            break
        fee = float(fee_per_share(price)) if fee_per_share else 0.0
        unit = price + fee
        shares = min(size * depth_haircut, left / unit)
        shares = int(shares * 100) / 100.0          # venues trade in hundredths of a share
        if shares <= 0:
            continue
        fills.append(Fill(price, shares, round(fee * shares, 6)))
        left -= shares * unit
    return fills


def simulate_sell(book: Book, shares: float, limit: float, fee_per_share=None, depth_haircut: float = 0.5) -> list[Fill]:
    """Sell up to `shares` into bids priced at or above `limit`."""
    fills: list[Fill] = []
    left = float(shares)
    for price, size in book.bids:
        if price < limit - 1e-9 or left <= 1e-9:
            break
        qty = int(min(size * depth_haircut, left) * 100) / 100.0
        if qty <= 0:
            continue
        fee = float(fee_per_share(price)) if fee_per_share else 0.0
        fills.append(Fill(price, qty, round(fee * qty, 6)))
        left -= qty
    return fills


def summarize(fills: list[Fill]) -> tuple[float, float, float]:
    """(shares, average price, total fee) of a list of fills."""
    shares = sum(f.shares for f in fills)
    if shares <= 0:
        return 0.0, 0.0, 0.0
    return shares, sum(f.price * f.shares for f in fills) / shares, sum(f.fee for f in fills)
