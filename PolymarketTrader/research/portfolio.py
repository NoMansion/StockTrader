"""What a rule would have done to an account: bets in time order, money locked until each market settles.

A mean return per bet says nothing about how fast capital turns over or how deep the holes get. This replays the
bets of one or more rules through a simple account:

  - a bet is opened at its entry time with a stake that is a fixed fraction of current equity, capped per event
    and by the cash on hand (no leverage); a market is entered once, whichever rule saw it first
  - the stake comes back, with the bet's after-fee return, when the market closes
  - open bets are carried at cost (no marking to market), so the equity curve only moves on settlements

Reported: total and annualised return, worst peak-to-trough drawdown, the share of time money was at work, and
the Sharpe ratio of weekly equity changes. In-sample and out-of-sample periods are simulated separately, each
starting from the same bankroll.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import panel
from backtest import Panel

DAY = 86400.0


@dataclass
class Account:
    bets: int = 0
    skipped: int = 0
    total: float = 0.0          # total return on the starting bankroll
    cagr: float = 0.0
    max_dd: float = 0.0
    sharpe: float = float("nan")
    exposure: float = 0.0       # average share of equity tied up in open bets
    years: float = 0.0

    def cells(self, prefix: str) -> dict:
        return {f"{prefix}_bets": self.bets, f"{prefix}_total": self.total, f"{prefix}_cagr": self.cagr,
                f"{prefix}_maxdd": self.max_dd, f"{prefix}_sharpe": self.sharpe, f"{prefix}_exposure": self.exposure,
                f"{prefix}_years": self.years}


def entries(p: Panel, rules: list[tuple[np.ndarray, str, str]]) -> np.ndarray:
    """Rows of the first qualifying bar of each market across all rules -> array of (entry ts, close ts, return,
    event code), sorted by entry time."""
    ts = p.col("ts").astype("float64")
    close = p.col("close_ts").astype("float64")
    best: dict[int, tuple[float, float, float, int]] = {}
    for mask, side, entry in rules:
        key = (side, entry)
        rows = p.first_per_market(mask & p.ok[key])
        r = p.r[key]
        for i in rows:
            t = int(p.ticker[i])
            if t not in best or ts[i] < best[t][0]:
                best[t] = (ts[i], max(close[i], ts[i] + DAY), float(r[i]), int(p.event[i]))
    out = np.array(sorted(best.values()), dtype="float64") if best else np.zeros((0, 4))
    return out


def simulate(bets: np.ndarray, stake_frac: float = 0.01, event_cap: float = 0.03, max_exposure: float = 0.5,
             bankroll: float = 1000.0, min_stake: float = 1.0) -> Account:
    acct = Account()
    if len(bets) == 0:
        return acct
    t0, t1 = bets[0, 0], max(bets[:, 1].max(), bets[-1, 0])
    cash = bankroll
    open_bets: list[tuple[float, float, float, int]] = []          # (close ts, stake, return, event)
    curve_t, curve_e = [t0], [bankroll]
    expo_area, last_t = 0.0, t0

    def settle(upto: float):
        nonlocal cash, open_bets
        open_bets.sort()
        while open_bets and open_bets[0][0] <= upto:
            close, stake, r, _ = open_bets.pop(0)
            cash += stake * (1.0 + r)
            curve_t.append(close)
            curve_e.append(cash + sum(b[1] for b in open_bets))

    for ts, close, r, ev in bets:
        settle(ts)
        staked = sum(b[1] for b in open_bets)
        equity = cash + staked
        expo_area += (staked / equity if equity > 0 else 0.0) * (ts - last_t)
        last_t = ts
        if equity <= 0:
            break
        in_event = sum(b[1] for b in open_bets if b[3] == ev)
        stake = min(stake_frac * equity, event_cap * equity - in_event, max_exposure * equity - staked, cash)
        if stake < min_stake:
            acct.skipped += 1
            continue
        cash -= stake
        open_bets.append((close, stake, r, int(ev)))
        acct.bets += 1
    settle(float("inf"))
    e = np.array(curve_e)
    acct.years = max((t1 - t0) / (365.25 * DAY), 1e-9)
    acct.total = e[-1] / bankroll - 1.0
    acct.cagr = (e[-1] / bankroll) ** (1.0 / acct.years) - 1.0 if e[-1] > 0 else -1.0
    acct.max_dd = float((1.0 - e / np.maximum.accumulate(e)).max())
    acct.exposure = expo_area / max(t1 - t0, 1.0)
    # weekly equity changes for a Sharpe ratio (equity is a step function of settlements)
    grid = np.arange(t0, t1 + 7 * DAY, 7 * DAY)
    idx = np.searchsorted(np.array(curve_t), grid, side="right") - 1
    w = e[np.clip(idx, 0, len(e) - 1)]
    rets = np.diff(w) / w[:-1]
    if len(rets) > 8 and rets.std() > 0:
        acct.sharpe = float(rets.mean() / rets.std() * np.sqrt(52))
    return acct


def run(p: Panel, rules: list[tuple[np.ndarray, str, str]], **kw) -> tuple[Account, Account]:
    """(in sample, out of sample): each period simulated on its own from a fresh bankroll."""
    b = entries(p, rules)
    if len(b) == 0:
        return Account(), Account()
    ins = b[b[:, 1] < panel.SPLIT_TS]
    oos = b[b[:, 1] >= panel.SPLIT_TS]
    return simulate(ins, **kw), simulate(oos, **kw)
