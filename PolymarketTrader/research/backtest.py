"""Backtest engine for mechanical rules on the Kalshi panel (research/panel.py).

A rule is: a condition on what was known at the end of a bar, a side (YES or NO), and an entry type (take the
next bar's opening quote, or rest a bid and count it only if the market trades through it). One entry per market:
the first bar on which the condition holds and an entry was possible. Positions are held to settlement.

Every result is reported twice, in sample (markets closing before 2026-04-01) and out of sample (after), with:
  n         bets (one per market)
  events    distinct events among them: the real sample size, because markets of one event move together
  ret       mean return per dollar staked, after fees
  t         ret divided by its standard error clustered by event
  win       share of bets that paid out
  cost      mean price paid per contract, fees included
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RET = {("yes", "tk"): "r_yes_tk", ("no", "tk"): "r_no_tk", ("yes", "mk"): "r_yes_mk", ("no", "mk"): "r_no_mk"}


@dataclass
class Sample:
    n: int = 0
    events: int = 0
    ret: float = float("nan")
    t: float = float("nan")
    win: float = float("nan")
    cost: float = float("nan")

    def cells(self, prefix: str) -> dict:
        return {f"{prefix}_n": self.n, f"{prefix}_events": self.events, f"{prefix}_ret": self.ret, f"{prefix}_t": self.t,
                f"{prefix}_win": self.win, f"{prefix}_cost": self.cost}


class Panel:
    """The observation table as plain arrays, plus the bookkeeping a fast evaluation needs."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.n = len(df)
        self.ticker = pd.factorize(df["ticker"], sort=False)[0]
        self.event = pd.factorize(df["event"], sort=False)[0]
        self.n_events = int(self.event.max()) + 1 if self.n else 0
        self.oos = df["oos"].to_numpy(bool)
        self.y = df["y"].to_numpy("float32")
        self.r = {k: df[col].to_numpy("float32") for k, col in RET.items()}
        if "r_pair_tk" in df:                       # the ladder pair trade: side "pair", entry "pair"
            self.r[("pair", "pair")] = df["r_pair_tk"].to_numpy("float32")
        self.ok = {k: ~np.isnan(v) for k, v in self.r.items()}
        # price paid per contract for each side and entry (before fees), for reporting
        self.px = {("yes", "tk"): df["n_ask_op"].to_numpy("float32"), ("no", "tk"): (1 - df["n_bid_op"]).to_numpy("float32"),
                   ("yes", "mk"): df["bid"].to_numpy("float32"), ("no", "mk"): (1 - df["ask"]).to_numpy("float32")}
        if "pair_cost" in df:
            self.px[("pair", "pair")] = df["pair_cost"].to_numpy("float32")

    def col(self, name: str) -> np.ndarray:
        return self.df[name].to_numpy()

    def first_per_market(self, mask: np.ndarray) -> np.ndarray:
        """Row numbers of the first True row of each market (rows are ordered by market, then time)."""
        idx = np.flatnonzero(mask)
        if idx.size == 0:
            return idx
        t = self.ticker[idx]
        keep = np.ones(idx.size, bool)
        keep[1:] = t[1:] != t[:-1]
        return idx[keep]

    def sample(self, rows: np.ndarray, r: np.ndarray, px: np.ndarray, pay: np.ndarray) -> Sample:
        n = rows.size
        if n == 0:
            return Sample()
        x = r[rows].astype("float64")
        mean = x.mean()
        ev = self.event[rows]
        sums = np.bincount(ev, weights=x - mean, minlength=self.n_events)
        k = int((np.bincount(ev, minlength=self.n_events) > 0).sum())
        se = np.sqrt((sums ** 2).sum()) / n * (np.sqrt(k / (k - 1)) if k > 1 else np.nan)
        return Sample(n=n, events=k, ret=float(mean), t=float(mean / se) if se and se > 0 else float("nan"),
                      win=float(pay[rows].mean()), cost=float(px[rows].mean()))

    def evaluate(self, mask: np.ndarray, side: str, entry: str, once: bool = True) -> tuple[Sample, Sample]:
        """(in sample, out of sample) for the rule 'when mask holds, buy `side` by `entry`'."""
        key = (side, entry)
        m = mask & self.ok[key]
        rows = self.first_per_market(m) if once else np.flatnonzero(m)
        pay = self.y if side == "yes" else (self.r[key] > 0).astype("float32") if side == "pair" else 1 - self.y
        o = self.oos[rows]
        return (self.sample(rows[~o], self.r[key], self.px[key], pay), self.sample(rows[o], self.r[key], self.px[key], pay))

    def evaluate_custom(self, mask: np.ndarray, r: np.ndarray, px: np.ndarray, pay: np.ndarray,
                        once: bool = True) -> tuple[Sample, Sample]:
        """As evaluate(), for a return column that is not one of the four standard ones (pair trades and the like)."""
        m = mask & ~np.isnan(r)
        rows = self.first_per_market(m) if once else np.flatnonzero(m)
        o = self.oos[rows]
        return self.sample(rows[~o], r, px, pay), self.sample(rows[o], r, px, pay)

    def fill_rate(self, mask: np.ndarray, side: str) -> float:
        """Of the markets where a resting order was placed (first bar the condition held), the share that filled."""
        placed = self.first_per_market(mask & self.df["quoted"].to_numpy(bool))
        if placed.size == 0:
            return float("nan")
        return float(self.ok[(side, "mk")][placed].mean())


def row(family: str, name: str, side: str, entry: str, ins: Sample, oos: Sample, **extra) -> dict:
    return {"family": family, "rule": name, "side": side, "entry": entry, **ins.cells("is"), **oos.cells("oos"), **extra}


def verdict(r: dict, min_events: int = 100, t_oos: float = 3.0, t_is: float = 2.0) -> str:
    """The promotion test from STATE.md. 'pass' needs both halves positive and significant on enough events."""
    if r["oos_events"] < min_events or r["is_events"] < min_events:
        return "thin"
    if r["is_ret"] > 0 and r["oos_ret"] > 0 and r["is_t"] >= t_is and r["oos_t"] >= t_oos:
        return "pass"
    if r["is_ret"] > 0 and r["oos_ret"] > 0 and r["oos_t"] >= 2.0:
        return "lead"
    if r["is_ret"] < 0 and r["oos_ret"] < 0 and r["is_t"] <= -t_is and r["oos_t"] <= -t_oos:
        return "loses"                      # reliably negative: the other side is worth a look
    return "no"
