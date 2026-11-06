"""Transaction cost models.

Why this exists: a flat slippage number is wrong in exactly the places a
liquidity-ranked universe reaches. Real cost depends on how big your order is
relative to what the stock trades in a day. With a per-stock cost in the
optimizer, thin names only get money if their expected return beats their
*actual* cost to trade for *your* account size — the min_price / top_k
thresholds become safety rails instead of the decision.

Model (square-root market impact, the standard retail-to-institutional form):

    cost_fraction(trade) = spread_bps/1e4            (half-spread, always paid)
                         + impact_coef · sigma_daily · sqrt(trade_$ / ADV_$)

where ADV_$ is the stock's trailing median daily dollar volume and sigma_daily
its daily return volatility. `impact_coef` ≈ 0.1 is a widely used default;
raise it if live fills come in worse than the backtest predicts.

All functions work on weight fractions of the portfolio plus `capital` ($).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class CostModel:
    kind: str = "impact"             # "impact" or "flat"
    flat_bps: float = 10.0           # used by "flat"; also the floor for "impact"
    spread_bps: float = 3.0          # half-spread paid on every trade (large caps ~1-3, small caps 10+)
    impact_coef: float = 0.1
    capital: float = 100_000.0       # account size; impact scales with it
    max_participation: float = 0.05  # don't plan to trade more than 5% of a stock's ADV in a day
    commission_per_trade: float = 0.0

    # ---- realised cost of a set of trades, as a fraction of portfolio value
    def trade_cost(self, delta_w: pd.Series, adv: pd.Series | None, sigma: pd.Series | None) -> float:
        d = delta_w.abs()
        d = d[d > 0]
        if d.empty:
            return 0.0
        n_trades = len(d)
        if self.kind == "flat" or adv is None or sigma is None:
            return float(d.sum() * self.flat_bps / 1e4 + self.commission_per_trade * n_trades / self.capital)
        a = adv.reindex(d.index)
        s = sigma.reindex(d.index)
        a = a.fillna(a.median() if a.notna().any() else 1e6).clip(lower=1e4)
        s = s.fillna(s.median() if s.notna().any() else 0.02).clip(lower=1e-4)
        trade_dollars = d * self.capital
        rate = self.spread_bps / 1e4 + self.impact_coef * s * np.sqrt(trade_dollars / a)
        rate = rate.clip(lower=self.flat_bps / 1e4)
        return float((d * rate).sum() + self.commission_per_trade * n_trades / self.capital)

    # ---- per-name linear coefficient for the optimizer (cost per unit weight traded)
    def linear_coeffs(self, names: pd.Index, adv: pd.Series | None, sigma: pd.Series | None, ref_delta_w: pd.Series | float = 0.01) -> pd.Series:
        """Linearise the sqrt cost at a reference trade size (weight fraction).

        Returns cost-per-unit-weight for each name, so the optimizer's L1 term
        c_i·|w_i − w0_i| matches the realised cost at that trade size.
        """
        if self.kind == "flat" or adv is None or sigma is None:
            return pd.Series(self.flat_bps / 1e4, index=names)
        ref = ref_delta_w.reindex(names).abs() if isinstance(ref_delta_w, pd.Series) else pd.Series(ref_delta_w, index=names)
        ref = ref.fillna(0.01).clip(lower=0.002)
        a = adv.reindex(names)
        s = sigma.reindex(names)
        a = a.fillna(a.median() if a.notna().any() else 1e6).clip(lower=1e4)
        s = s.fillna(s.median() if s.notna().any() else 0.02).clip(lower=1e-4)
        rate = self.spread_bps / 1e4 + self.impact_coef * s * np.sqrt(ref * self.capital / a)
        return rate.clip(lower=self.flat_bps / 1e4)

    # ---- hard tradability cap: max weight change per day given ADV participation
    def max_trade_weight(self, names: pd.Index, adv: pd.Series | None) -> pd.Series | None:
        if adv is None:
            return None
        a = adv.reindex(names).fillna(0.0)
        return (self.max_participation * a / self.capital).clip(lower=0.0)


def dollar_adv(close: pd.DataFrame, volume: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """Trailing median daily dollar volume, date x ticker."""
    return (close * volume).rolling(lookback, min_periods=lookback // 2).median()
