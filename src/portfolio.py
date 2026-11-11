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
    # "equal": fill top_n with an equal number of names per sector (best-ranked
    # within each), remaining slots from the overall ranking. None = plain top-N.
    # "cap": plain top-N, but no sector may take more than `sector_cap` of the slots.
    sector_mode: str | None = None
    sector_cap: float | None = None                          # "cap" only, e.g. 0.25 = 10 of 40 names
    sectors: dict | None = field(default=None, repr=False)   # ticker -> sector name


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
    if rules.sector_mode == "equal" and rules.sectors:
        return _select_equal_sector(s, rules.top_n, rules.sectors)
    if rules.sector_mode == "cap":
        if rules.sector_cap is None or not 0 < rules.sector_cap <= 1:
            raise ValueError(f"sector_mode 'cap' needs 0 < sector_cap <= 1, got {rules.sector_cap!r}")
        if rules.sectors:
            return _select_capped_sector(s, rules.top_n, rules.sectors, rules.sector_cap)
    if rules.sector_mode not in (None, "equal", "cap"):
        raise ValueError(f"unknown sector_mode: {rules.sector_mode}")
    return s.head(rules.top_n)


def _select_capped_sector(s: pd.Series, top_n: int, sectors: dict, cap_frac: float) -> pd.Series:
    """Walk the ranking from the top and take a name unless its sector already holds
    floor(cap_frac * top_n) slots (at least 1). Names with no sector share one "Unknown" bucket.
    Sweep 2026-11-10: on the SUE + FCF-yield ranker a 20-30% cap beat both the equal split and no rule."""
    cap = max(1, int(np.floor(cap_frac * top_n)))
    counts: dict = {}
    keep: list = []
    for t in s.index:
        g = sectors.get(t, "Unknown")
        if counts.get(g, 0) < cap:
            keep.append(t)
            counts[g] = counts.get(g, 0) + 1
        if len(keep) >= top_n:
            break
    return s.loc[keep]


def _select_equal_sector(s: pd.Series, top_n: int, sectors: dict) -> pd.Series:
    """Equal slots per known sector (top_n // n_sectors each, best-ranked names
    within the sector), then fill what is left from the overall ranking.
    Names with no sector only compete for the leftover slots."""
    sec = np.array([sectors.get(t, "Unknown") for t in s.index])
    groups = [g for g in sorted(set(sec)) if g != "Unknown"]
    per = max(1, top_n // max(1, len(groups)))
    keep: list = []
    for g in groups:
        keep += list(s.index[sec == g][:per])
    rest = s[~s.index.isin(keep)]
    keep += list(rest.index[: max(0, top_n - len(keep))])
    return s.loc[keep].sort_values(ascending=False)


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

    cur, tgt = current.to_numpy(dtype=float), target.to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        drift = np.abs(cur - tgt) / tgt
    new = pd.Series(
        np.where(tgt == 0, 0.0,                                   # exit (or never held)
                 np.where(cur == 0, tgt,                          # enter
                          np.where(drift > rules.min_trade_pct, tgt, cur))),   # add / trim / hold
        index=current.index)

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
    exited = trades.index[(current[trades.index] > 0).to_numpy() & (new[trades.index] == 0).to_numpy()]
    for t in exited:
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
