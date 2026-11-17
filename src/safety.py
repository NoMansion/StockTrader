"""Safety limits checked right before the daily job sends orders (built 2026-11-17 for the move to a real account).

A limit that trips means NO orders that day: a skipped day costs almost nothing, a wrong trade can cost a lot. The
job logs the reason to data/run_daily_errors.log, exits with code 4 and leaves the saved state untouched, so the
next run retries normally. The same checks run on the paper account and in every dry run.

Stops (the whole day is skipped):
  live confirm     orders to a REAL account (ALPACA_PAPER not "true") need LIVE_TRADING_CONFIRM=yes-real-money
  kill switch      the file live.safety.kill_switch (data/STOP) exists
  equity           equity <= 0, or it moved more than max_equity_change since the last logged session
  positions        the number of stock targets is outside [min_positions, max_positions]
  order size       one stock order above max_order_pct of equity (sleeve ETFs: max_sleeve_order_pct)
  turnover         stock buys + sells above max_stock_turnover of equity, or everything above max_total_turnover
Per-name fixes (the rest of the day trades):
  price            a stock with no price, or whose price moved more than max_price_move since the previous close,
                   is not traded today (bad data or a corporate action the feed has not adjusted yet)
  cash             buys that need more cash than the account has after its sells are scaled down (no margin)

The defaults sit just above what the live model has done in its backtests (2000-2026, worst day: stock turnover
0.67 of equity, sleeve weight change 0.81, 38-45 positions). `allow_rebuild` (run_daily --allow-full-rebuild)
waives the equity and turnover limits for one run: after a paper-account reset, a deposit above the equity limit,
or a model switch that replaces most of the book.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

LIVE_CONFIRM_ENV = "LIVE_TRADING_CONFIRM"
LIVE_CONFIRM_VALUE = "yes-real-money"
EXIT_CODE = 4

DEFAULTS = {
    "kill_switch": "data/STOP",
    "max_equity_change": 0.25,
    "min_positions": 30,
    "max_positions": 60,
    "max_order_pct": 0.12,
    "max_sleeve_order_pct": 0.85,
    "max_stock_turnover": 0.9,
    "max_total_turnover": 1.8,
    "max_price_move": 0.5,
}


class SafetyStop(RuntimeError):
    """A safety limit tripped: send no orders today."""


@dataclass
class SafetyResult:
    ok: bool
    stops: list[str] = field(default_factory=list)       # reasons the whole day is skipped
    warnings: list[str] = field(default_factory=list)    # per-name fixes; the day still trades
    targets: pd.Series | None = None                     # targets after the per-name fixes
    skip: set = field(default_factory=set)               # names not to trade today (price check)
    stats: dict = field(default_factory=dict)

    def summary(self) -> str:
        s = self.stats
        head = (f"Safety checks: {'PASS' if self.ok else 'STOP'} | equity ${s.get('equity', 0):,.0f}"
                + (f" ({s['equity_change']:+.1%} vs last session)" if s.get("equity_change") is not None else "")
                + f" | {s.get('n_stocks', 0)} stocks | largest stock order {s.get('max_stock_order', 0):.1%}"
                + f" | turnover stocks {s.get('stock_turnover', 0):.1%}, all {s.get('total_turnover', 0):.1%}")
        lines = [head] + [f"  STOP: {x}" for x in self.stops] + [f"  note: {x}" for x in self.warnings]
        return "\n".join(lines)


def settings(cfg: dict | None) -> dict:
    """live.safety from the config over the defaults."""
    out = dict(DEFAULTS)
    out.update(((cfg or {}).get("live") or {}).get("safety") or {})
    return out


def is_paper() -> bool:
    return os.environ.get("ALPACA_PAPER", "true").lower() == "true"


def live_confirmed() -> bool:
    return os.environ.get(LIVE_CONFIRM_ENV, "") == LIVE_CONFIRM_VALUE


def require_live_confirmation() -> None:
    """Raise SafetyStop before any order goes to a real-money account without the explicit confirmation."""
    if not is_paper() and not live_confirmed():
        raise SafetyStop(f"ALPACA_PAPER is not 'true' (real money) but {LIVE_CONFIRM_ENV} is not set to "
                         f"'{LIVE_CONFIRM_VALUE}' in .env: no orders sent")


def previous_equity(path: Path, today) -> float | None:
    """Equity of the last logged session before `today` (data/equity.csv), None without one."""
    if not Path(path).exists():
        return None
    d = pd.read_csv(path)
    if d.empty or "equity" not in d:
        return None
    d = d[pd.to_datetime(d["date"]) < pd.Timestamp(today).normalize()]
    return float(d["equity"].iloc[-1]) if len(d) else None


def check_orders(targets: pd.Series, positions: pd.Series, equity: float, prev_equity: float | None,
                 prices: pd.Series | None, prev_prices: pd.Series | None, cfg: dict | None = None,
                 sleeve_assets=(), skip=(), allow_rebuild: bool = False, root: Path | str = ".") -> SafetyResult:
    """Check today's targets (ticker -> weight of equity) against the account (ticker -> market value $).
    `skip`: names the rules already leave untouched (no-trade band); they are not counted as trades."""
    st = settings(cfg)
    sleeve = set(sleeve_assets)
    skip = set(skip)
    res = SafetyResult(ok=True, targets=targets.astype(float).copy())
    stops, warns = res.stops, res.warnings
    t = res.targets
    pos = positions.astype(float) if positions is not None else pd.Series(dtype=float)

    # live confirmation and the kill switch first: nothing else matters if either is set
    if not is_paper() and not live_confirmed():
        stops.append(f"real-money account (ALPACA_PAPER is not 'true') without {LIVE_CONFIRM_ENV}={LIVE_CONFIRM_VALUE}")
    ks = Path(root) / st["kill_switch"] if st.get("kill_switch") else None
    if ks is not None and ks.exists():
        stops.append(f"kill switch {st['kill_switch']} exists: delete it to trade again")

    # equity
    res.stats["equity"] = float(equity)
    if not equity or equity <= 0 or equity != equity:
        stops.append(f"account equity is {equity!r}")
        res.ok = False
        return res
    chg = None if not prev_equity else equity / prev_equity - 1
    res.stats["equity_change"] = chg
    if chg is not None and abs(chg) > st["max_equity_change"]:
        msg = f"equity ${equity:,.0f} is {chg:+.1%} vs the last session's ${prev_equity:,.0f} (limit {st['max_equity_change']:.0%})"
        (warns if allow_rebuild else stops).append(msg + (" - allowed by --allow-full-rebuild" if allow_rebuild else
                                                          "; after a deposit/withdrawal or a reset run with --allow-full-rebuild"))

    # number of stock targets
    stocks = t[(t > 0) & ~t.index.isin(list(sleeve))]
    res.stats["n_stocks"] = int(len(stocks))
    if not st["min_positions"] <= len(stocks) <= st["max_positions"]:
        stops.append(f"{len(stocks)} stock targets, outside the allowed {st['min_positions']}-{st['max_positions']}")

    # price check: stocks only (sleeve ETFs have no price in the live frame); a held name with a bad price is
    # neither bought nor sold today
    names = [n for n in t.index.union(pos.index) if n not in sleeve and n not in skip]
    for n in names:
        p = float(prices.get(n, float("nan"))) if prices is not None else float("nan")
        q = float(prev_prices.get(n, float("nan"))) if prev_prices is not None else float("nan")
        wants = float(t.get(n, 0.0)) * equity - float(pos.get(n, 0.0))
        if abs(wants) < 1.0:
            continue
        if not p > 0:
            if wants > 0:    # a sell does not need our price (the broker exits by quantity); a buy does
                res.skip.add(n)
                warns.append(f"{n}: no price today, buy of ${wants:,.0f} skipped")
            continue
        if q > 0 and abs(p / q - 1) > st["max_price_move"]:
            res.skip.add(n)
            warns.append(f"{n}: price {q:.2f} -> {p:.2f} ({p / q - 1:+.0%}) in one day, not traded today "
                         f"(${wants:+,.0f} skipped)")

    # deltas as the broker will compute them, without the skipped names
    allnames = [n for n in t.index.union(pos.index) if n not in skip and n not in res.skip]
    delta = pd.Series({n: float(t.get(n, 0.0)) * equity - float(pos.get(n, 0.0)) for n in allnames}, dtype=float)
    delta = delta[delta.abs() >= 1.0]

    # order size and turnover (fractions of equity), on the orders as the rules asked for them: a huge order is a
    # stop even if the cash check below would have shrunk it
    d = delta.abs() / equity
    ds, dz = d[~d.index.isin(list(sleeve))], d[d.index.isin(list(sleeve))]
    res.stats.update(max_stock_order=float(ds.max()) if len(ds) else 0.0,
                     max_sleeve_order=float(dz.max()) if len(dz) else 0.0,
                     stock_turnover=float(ds.sum()), total_turnover=float(d.sum()))
    big = ds[ds > st["max_order_pct"]]
    if len(big):
        stops.append("stock order(s) above " + f"{st['max_order_pct']:.0%} of equity: "
                     + ", ".join(f"{n} {v:.1%}" for n, v in big.sort_values(ascending=False).head(5).items()))
    bigz = dz[dz > st["max_sleeve_order_pct"]]
    if len(bigz):
        stops.append("sleeve order(s) above " + f"{st['max_sleeve_order_pct']:.0%} of equity: "
                     + ", ".join(f"{n} {v:.1%}" for n, v in bigz.items()))
    for key, val, label in (("max_stock_turnover", float(ds.sum()), "stock"),
                            ("max_total_turnover", float(d.sum()), "total")):
        if val > st[key] + 1e-9:
            msg = f"{label} turnover {val:.0%} of equity above the {st[key]:.0%} limit"
            (warns if allow_rebuild else stops).append(msg + (" - allowed by --allow-full-rebuild" if allow_rebuild
                                                              else "; a reset or model switch needs --allow-full-rebuild"))

    # cash: buys may use the cash on hand plus today's sells, never margin
    cash = equity - float(pos.sum())
    buys, sells = float(delta[delta > 0].sum()), float(-delta[delta < 0].sum())
    room = cash + sells
    if buys > 0 and buys > room + 1.0:
        scale = max(room, 0.0) / buys
        for n in delta[delta > 0].index:
            t.loc[n] = (float(pos.get(n, 0.0)) + float(delta[n]) * scale) / equity
        warns.append(f"buys of ${buys:,.0f} exceed cash ${cash:,.0f} + sells ${sells:,.0f}: scaled to {scale:.0%}")
    res.ok = not stops
    return res
