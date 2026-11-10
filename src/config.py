from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def build_rules(cfg: dict[str, Any], top_n: int | None = None, sectors: dict | None = None):
    """Rules (+ OptimizerConfig when sizing == 'optimizer') from a config dict.
    `sectors` (ticker -> sector) is required when portfolio.sector_mode is set."""
    from .optimizer import OptimizerConfig
    from .portfolio import Rules

    p = cfg["portfolio"]
    opt = None
    if p["sizing"] == "optimizer":
        o = cfg.get("optimizer", {})
        opt = OptimizerConfig(
            risk_aversion=o.get("risk_aversion", 8.0), tc_bps=o.get("tc_bps", 20.0),
            tc_multiplier=o.get("tc_multiplier", 1.5),
            cov_lookback=o.get("cov_lookback", 120), shrinkage=o.get("shrinkage", 0.5),
            ic_default=o.get("ic_default", 0.03), ic_floor=o.get("ic_floor", 0.0),
            max_weight=p["max_weight"], cash_buffer=p["cash_buffer"],
            min_weight=o.get("min_weight", 0.005), max_positions=o.get("max_positions"),
        )
    return Rules(
        top_n=top_n or p["top_n"], sizing=p["sizing"], max_weight=p["max_weight"],
        min_trade_pct=p["min_trade_pct"], cash_buffer=p["cash_buffer"],
        reentry_cooldown_days=p["reentry_cooldown_days"], optimizer=opt,
        sector_mode=p.get("sector_mode"), sectors=sectors,
    )


def build_sleeve(cfg: dict[str, Any]):
    """SleeveConfig from portfolio.sleeve, or None when unset/null."""
    s = cfg["portfolio"].get("sleeve")
    if not s:
        return None
    from .sleeve import SleeveConfig

    return SleeveConfig(**s)


def build_cost_model(cfg: dict[str, Any]):
    from .costs import CostModel

    c = cfg.get("costs", {})
    return CostModel(
        kind=c.get("model", "impact"), flat_bps=c.get("flat_bps", c.get("slippage_bps", 10.0)),
        spread_bps=c.get("spread_bps", 3.0), impact_coef=c.get("impact_coef", 0.1),
        capital=float(c.get("capital", 100_000)), max_participation=c.get("max_participation", 0.05),
        commission_per_trade=c.get("commission_per_trade", 0.0),
    )


def build_backtest_config(cfg: dict[str, Any], ranker: str | None = None, rebalance: int | None = None):
    from .backtest import AutoTune, BacktestConfig

    m, p, a = cfg["model"], cfg["portfolio"], cfg.get("auto_tune", {})
    return BacktestConfig(
        ranker=ranker or m["type"], ranker_weights=m.get("weights"), horizon_days=m["horizon_days"],
        retrain_every_days=m["retrain_every_days"], train_window_days=m["train_window_days"],
        min_train_days=m["min_train_days"], rebalance_every_days=rebalance or p["rebalance_every_days"],
        cost_model=build_cost_model(cfg), sleeve=build_sleeve(cfg), cash_yield=bool(p.get("cash_yield", False)),
        auto_tune=AutoTune(
            enabled=a.get("enabled", False), risk_aversion=[float(x) for x in a.get("risk_aversion", [4, 8, 16])],
            tc_multiplier=[float(x) for x in a.get("tc_multiplier", [1.0, 1.5, 2.5])],
            tune_window=a.get("tune_window", 252), tune_rebalance_every=a.get("tune_rebalance_every", 5),
        ),
    )
