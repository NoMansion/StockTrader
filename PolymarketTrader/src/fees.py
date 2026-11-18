"""Trading fees. Both Polymarket venues and Kalshi charge takers a fee shaped like

    fee per share = rate * p * (1 - p)

which peaks at p = 0.50 and vanishes toward 0 and 1. Makers (resting limit orders) pay nothing on standard
markets. The rate depends on the venue, the market category and, on Polymarket US, the account's 30-day volume.

The rates below are the ones found in the November 2026 research (reports/). They change often: the live rate
for a market should be read from the venue (see venue.py) and these are only the fallback. When in doubt the
code uses the HIGHER number, so a fee surprise can only make a real fill cheaper than planned, never dearer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Fallback taker rates, fee = rate * p * (1 - p) per share.
POLYMARKET_US_ENTRY_TIER = 0.095       # under $10k of 30-day volume
POLYMARKET_INTL = {"crypto": 0.07, "sports": 0.05, "politics": 0.04, "finance": 0.04, "economics": 0.04,
                   "tech": 0.04, "culture": 0.04, "geopolitics": 0.0}
KALSHI = 0.07


@dataclass
class FeeModel:
    taker_rate: float = POLYMARKET_US_ENTRY_TIER
    maker_rate: float = 0.0
    by_category: dict[str, float] = field(default_factory=dict)   # category -> taker rate override

    @classmethod
    def from_config(cls, cfg: dict | None) -> "FeeModel":
        f = (cfg or {}).get("fees") or {}
        return cls(taker_rate=float(f.get("taker_rate", POLYMARKET_US_ENTRY_TIER)),
                   maker_rate=float(f.get("maker_rate", 0.0)),
                   by_category={str(k).lower(): float(v) for k, v in (f.get("by_category") or {}).items()})

    def rate(self, category: str | None = None, maker: bool = False, market_rate: float | None = None) -> float:
        if maker:
            return self.maker_rate
        if market_rate is not None:                     # the venue's own number for this market wins
            return max(float(market_rate), 0.0)
        return self.by_category.get((category or "").lower(), self.taker_rate)

    def per_share(self, price: float, category: str | None = None, maker: bool = False,
                  market_rate: float | None = None) -> float:
        """Fee in dollars for one share traded at `price`."""
        if not 0.0 < price < 1.0:
            return 0.0
        return self.rate(category, maker, market_rate) * price * (1.0 - price)

    def fn(self, category: str | None = None, maker: bool = False, market_rate: float | None = None):
        """price -> fee per share, for the fill simulator."""
        return lambda price: self.per_share(price, category, maker, market_rate)
