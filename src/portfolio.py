"""Your portfolio rules, as pure functions on weights.

Each rebalance:
  1. Rank the universe by score; the top-N is the "ranking".
  2. Names in the ranking get a target weight (sizing rule below).
  3. Held names that fell out of the ranking → target 0 (full exit).
  4. Held names still in the ranking → add if below target, trim if above,
     but only if the drift exceeds `min_trade_pct` of target (anti-churn band).
  5. Names that just exited can't be re-bought for `reentry_cooldown_days`.

Sizing rules:
  "rank"        — weight grows with rank inside the top-N. This encodes
                  "if it goes up buy more, if it goes down sell some": a
                  rising stock climbs the ranking → bigger target → add.
  "equal"       — 1/N
  "inverse_vol" — risk parity-ish; low-vol names get more weight
All are capped at `max_weight` and scaled to (1 - cash_buffer).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .optimizer import OptimizerConfig, allocate


@dataclass
class Rules:
    top_n: int = 20
    sizing: str = "rank"            # "rank" | "equal" | "inverse_vol" | "optimizer"
    max_weight: float = 0.10
    min_trade_pct: float = 0.20
    cash_buffer: float = 0.02
    reentry_cooldown_days: int = 5
    optimizer: "OptimizerConfig | None" = None   # used when sizing == "optimizer"


@dataclass
class State:
    """Mutable bookkeeping carried between rebalances."""
    weights: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    last_exit: dict[str, pd.Timestamp] = field(default_factory=dict)


def _cap_and_scale(w: pd.Series, cap: float, total: float) -> pd.Series:
    """Scale to `total`, cap each at `cap`, redistribute excess, repeat."""
    w = w.clip(lower=0)
    if w.sum() <= 0:
        return w * 0
    for _ in range(50):
        w = w / w.sum() * total
        over = w > cap
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        under = ~over
        if under.sum() == 0 or w[under].sum() <= 0:
            break
        w[under] += excess * w[under] / w[under].sum()
    return w


def size_positions(scores: pd.Series, vol: pd.Series | None, rules: Rules) -> pd.Series:
    """Target weights for the names in `scores` (already the chosen top-N)."""
    n = len(scores)
    if n == 0:
        return pd.Series(dtype=float)
    if rules.sizing == "equal":
        raw = pd.Series(1.0, index=scores.index)
    elif rules.sizing == "inverse_vol":
        v = vol.reindex(scores.index).replace(0, np.nan)
        raw = (1.0 / v).fillna((1.0 / v).median())
    elif rules.sizing == "rank":
        raw = scores.rank(ascending=True)  # 1..n, best name gets n
    else:
        raise ValueError(f"unknown sizing: {rules.sizing}")
    return _cap_and_scale(raw, rules.max_weight, 1.0 - rules.cash_buffer)


def select_top(scores: pd.Series, rules: Rules, state: State, today: pd.Timestamp) -> pd.Series:
    """Top-N by score, excluding names in re-entry cooldown (unless already held)."""
    s = scores.dropna().sort_values(ascending=False)
    held = set(state.weights[state.weights > 0].index)
    blocked = {
        t for t, d in state.last_exit.items()
        if t not in held and (today - d).days < rules.reentry_cooldown_days
    }
    s = s[~s.index.isin(blocked)]
    return s.head(rules.top_n)


def rebalance(
    scores: pd.Series,
    vol: pd.Series | None,
    rules: Rules,
    state: State,
    today: pd.Timestamp,
    returns_window: pd.DataFrame | None = None,
    ic: float = np.nan,
    adv: pd.Series | None = None,
    cost_model=None,
) -> tuple[pd.Series, pd.Series, State]:
    """Apply the rules once.

    Returns (new_weights, trades, new_state). `trades` is the weight delta per
    ticker (positive = buy). Weights are fractions of portfolio value.

    With sizing == "optimizer" (Stage B) the top-N / hold-band rules are
    bypassed: the optimizer decides count and size from scores, the risk
    model (`returns_window`) and the trailing IC, with turnover controlled by
    its transaction-cost penalty instead of `min_trade_pct`.
    """
    current = state.weights.reindex(scores.index.union(state.weights.index)).fillna(0.0)

    if rules.sizing == "optimizer":
        if returns_window is None:
            raise ValueError("optimizer sizing needs returns_window")
        cfg = rules.optimizer or OptimizerConfig(max_weight=rules.max_weight, cash_buffer=rules.cash_buffer)
        new = allocate(scores, returns_window, current, ic, cfg, adv=adv, cost_model=cost_model).reindex(current.index).fillna(0.0)
        trades = (new - current)
        trades = trades[trades.abs() > 1e-9]
        new_state = State(weights=new[new > 0].copy(), last_exit=dict(state.last_exit))
        for t in trades.index:
            if current[t] > 0 and new[t] == 0:
                new_state.last_exit[t] = today
        return new[new > 0], trades, new_state

    chosen = select_top(scores, rules, state, today)
    target = size_positions(chosen, vol, rules).reindex(current.index).fillna(0.0)

    new = current.copy()
    for t in current.index:
        cur, tgt = current[t], target[t]
        if tgt == 0:
            new[t] = 0.0                                    # exit (or never held)
        elif cur == 0:
            new[t] = tgt                                    # enter
        else:
            drift = abs(cur - tgt) / tgt
            new[t] = tgt if drift > rules.min_trade_pct else cur   # add / trim / hold

    # Held-but-untouched names keep their drifted weight, so the total can
    # exceed the budget. Cash is finite: scale down the *buys* to fit.
    budget = 1.0 - rules.cash_buffer
    if new.sum() > budget + 1e-12:
        buys = new > current
        excess = new.sum() - budget
        buy_room = (new[buys] - current[buys]).sum()
        if buy_room > 0:
            k = max(0.0, 1.0 - excess / buy_room)
            new[buys] = current[buys] + (new[buys] - current[buys]) * k

    trades = (new - current)
    trades = trades[trades.abs() > 1e-9]

    new_state = State(weights=new[new > 0].copy(), last_exit=dict(state.last_exit))
    for t in trades.index:
        if current[t] > 0 and new[t] == 0:
            new_state.last_exit[t] = today
    return new[new > 0], trades, new_state


def drift_weights(weights: pd.Series, returns: pd.Series) -> pd.Series:
    """Weights after one day of returns (no trading). Cash is implicit."""
    if weights.empty:
        return weights
    r = returns.reindex(weights.index).fillna(0.0)
    grown = weights * (1 + r)
    port_ret = grown.sum() + (1 - weights.sum())  # cash earns 0
    return grown / port_ret
