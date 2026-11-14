"""Idle-cash sleeve and cash-yield accounting.

The exposure layer (src/exposure.py) often leaves 40-70% of the book in cash. The sleeve
puts that idle cash (above the base cash buffer) into a small set of defensive ETFs instead
of leaving it uninvested. The Nov 2026 sweep found an always-on equal split of IEF and GLD
the most robust choice: +0.14 Sharpe and +2.8 pts CAGR over 26 stitched years, worst year
-12%. Adding TLT raised the 2022 loss to -18%; trend/momentum rules on the sleeve hurt.

Timing matches the stock book: sleeve weights set at the close of day t earn the asset
return on t+1. Pre-ETF history is spliced from index returns (SPLICE) so 2000-2004 can be
backtested; live trading only ever touches the ETF itself.

Budget. By default the sleeve only takes the cash the exposure layer leaves above the base
cash buffer (idle = 1 - stocks - cash_buffer). With `full: true` it takes everything the stock
book does not hold minus a small `base` buffer (idle = 1 - stocks - base), so a large
cash_buffer becomes a stock/sleeve split: the Nov 2026 hybrid leader runs cash_buffer 0.67 with
an always-equal SPY/IEF/GLD sleeve, i.e. about one quarter momentum stocks and three quarters
balanced ETFs. Without `full` that configuration would leave 65% in T-bills.

Config (config.yaml):
    portfolio:
      sleeve: {assets: [IEF, GLD], rule: always_eq, frac: 1.0}   # null = off
      sleeve: {assets: [SPY, IEF, GLD], rule: always_eq, full: true, base: 0.02}   # hybrid
      cash_yield: false      # backtest accounting only: idle cash earns the 13-week T-bill yield
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import exposure as _expo

# asset -> (ETF symbol, fallback index whose returns stand in before the ETF existed; None = cash)
SPLICE: dict[str, tuple[str, str | None]] = {
    "TLT": ("TLT", "$USBIG"), "IEF": ("IEF", "$USBIG"), "LQD": ("LQD", "$USBIG"),
    "SHY": ("SHY", None), "GLD": ("GLD", "$BCOMPR"), "BIL": ("BIL", None), "SGOV": ("SGOV", None),
    "SPY": ("SPY", None), "QQQ": ("QQQ", None), "IWM": ("IWM", None), "EFA": ("EFA", None),
    "EEM": ("EEM", None), "DBC": ("DBC", "$BCOMPR"), "VNQ": ("VNQ", None), "TIP": ("TIP", "$USBIG"),
}
TBILL_SYMBOL = "%IRX"      # 13-week T-bill discount yield, in percent


@dataclass
class SleeveConfig:
    assets: tuple[str, ...] = ("IEF", "GLD")
    rule: str = "always_eq"          # always_eq | trend_eq | momN (N months, trend-filtered) | rp (inverse 63-day vol)
    frac: float = 1.0                # share of idle cash the sleeve uses
    cost_bps: float = 5.0            # one-way cost per sleeve trade in the backtest
    full: bool = False               # True: idle = 1 - stocks - base (cash_buffer becomes a stock/sleeve split)
    base: float = 0.02               # the small cash buffer kept when full is True

    def __post_init__(self):
        self.assets = tuple(self.assets)
        unknown = [a for a in self.assets if a not in SPLICE]
        if unknown:
            raise ValueError(f"no splice entry for sleeve asset(s) {unknown}; add to src.sleeve.SPLICE")


def sleeve_prices(assets: tuple[str, ...] | list[str], index: pd.DatetimeIndex) -> pd.DataFrame:
    """Growth-of-1 price series per asset on `index`: the ETF's own returns where it traded,
    the fallback index's returns before that (flat where neither exists)."""
    symbols = sorted({s for a in assets for s in SPLICE[a] if s})
    raw = _expo.EXT_LOADER(symbols)
    raw.index = pd.to_datetime(raw.index)
    full = raw.reindex(raw.index.union(index)).ffill().reindex(index)
    out = {}
    for a in assets:
        etf, fb = SPLICE[a]
        r = full[etf].pct_change()
        if fb:
            have = full[etf].notna() & full[etf].shift(1).notna()
            r = r.where(have, full[fb].pct_change())
        out[a] = (1.0 + r.fillna(0.0)).cumprod()
    return pd.DataFrame(out, index=index)


def sleeve_allocation(prices: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Asset weights (rows sum to <= 1) under `rule`, using prices up to each date."""
    assets = list(prices.columns)
    if rule == "always_eq":
        return pd.DataFrame(1.0 / len(assets), index=prices.index, columns=assets)
    if rule == "rp":
        # inverse 63-day volatility (known at t), as the sweep's _sleeve_alloc "rp" (ranks 201-2500 model, 2026-11-14);
        # before any asset has 40 days of returns: equal split
        iv = 1.0 / prices.pct_change().rolling(63, min_periods=40).std().replace(0, np.nan)
        w = iv.div(iv.sum(axis=1).replace(0, np.nan), axis=0)
        none = w.isna().all(axis=1)
        return w.fillna(0.0).where(~none, 1.0 / len(assets), axis=0)
    trend = (prices / prices.shift(252) - 1) > 0
    if rule == "trend_eq":
        aw = trend.astype(float)
        return aw.div(aw.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    if rule.startswith("mom") and rule[3:].isdigit():
        m = (prices / prices.shift(21 * int(rule[3:])) - 1).where(trend)
        pick = m.fillna(-np.inf).idxmax(axis=1).where(m.notna().any(axis=1))
        return pd.get_dummies(pick).reindex(columns=assets, fill_value=0).astype(float)
    raise ValueError(f"unknown sleeve rule: {rule}")


def sleeve_buffer(cfg: SleeveConfig, base_cash_buffer: float) -> float:
    """The cash the sleeve must leave untouched: the book's cash_buffer, or `base` when `full`."""
    return float(cfg.base) if cfg.full else float(base_cash_buffer)


def idle_cash(invested: pd.Series | float, base_cash_buffer: float, frac: float) -> pd.Series | float:
    """Cash above the base buffer that the sleeve may use."""
    idle = 1.0 - invested - float(base_cash_buffer)
    idle = idle.clip(lower=0.0) if isinstance(idle, pd.Series) else max(idle, 0.0)
    return idle * float(frac)


def apply_sleeve(result, base_cash_buffer: float, cfg: SleeveConfig, prices: pd.DataFrame | None = None):
    """Add the sleeve's daily return to a BacktestResult (columns sleeve_ret, sleeve_w; ret adjusted)."""
    idx = result.daily.index
    px = prices.reindex(idx) if prices is not None else sleeve_prices(cfg.assets, idx)
    rets = px.pct_change().fillna(0.0)
    aw = sleeve_allocation(px, cfg.rule)
    invested = result.weights.reindex(idx).fillna(0.0).sum(axis=1)
    w = aw.mul(idle_cash(invested, sleeve_buffer(cfg, base_cash_buffer), cfg.frac), axis=0)   # set at close t ...
    w_prev = w.shift(1).fillna(0.0)                                         # ... earns t+1
    sleeve_ret = (w_prev * rets).sum(axis=1) - (w - w_prev).abs().sum(axis=1) * cfg.cost_bps / 1e4
    result.daily["sleeve_ret"] = sleeve_ret
    result.daily["sleeve_w"] = w_prev.sum(axis=1)
    result.daily["ret"] = result.daily["ret"] + sleeve_ret
    return result


def apply_cash_yield(result, tbill_pct: pd.Series | None = None):
    """Idle cash (not in stocks, not in the sleeve) earns the 13-week T-bill yield known a day earlier."""
    idx = result.daily.index
    if tbill_pct is None:
        tbill_pct = _expo.external_series([TBILL_SYMBOL], idx)[TBILL_SYMBOL]
    invested = result.weights.reindex(idx).fillna(0.0).sum(axis=1).shift(1).fillna(0.0)
    sleeve_w = result.daily["sleeve_w"] if "sleeve_w" in result.daily.columns else 0.0
    idle = (1.0 - invested - sleeve_w).clip(lower=0.0)
    daily_rate = tbill_pct.reindex(idx).shift(1).fillna(0.0) / 100.0 / 252.0
    result.daily["cash_ret"] = idle * daily_rate
    result.daily["ret"] = result.daily["ret"] + result.daily["cash_ret"]
    return result


def live_sleeve_targets(stock_weights: pd.Series, base_cash_buffer: float, cfg: SleeveConfig,
                        prices: pd.DataFrame) -> pd.Series:
    """Today's sleeve target weights given today's stock targets (both as fractions of equity)."""
    idle = idle_cash(float(stock_weights.sum()), sleeve_buffer(cfg, base_cash_buffer), cfg.frac)
    aw = sleeve_allocation(prices, cfg.rule).iloc[-1]
    return (aw * idle).round(6)
