"""Safety limits, checked by deterministic code after the model has given its probability and before any order.

The model never sees these limits and cannot change them: it returns a number and a rationale, nothing else. A
limit that trips means no new positions; a skipped cycle costs nothing, a wrong trade costs money. Exits of
existing positions stay allowed under every account-level stop except the kill switch and the live confirmation,
so a halted account can still reduce risk.

Account-level stops (no new positions this cycle):
  live confirm      mode "live" needs PMT_LIVE_CONFIRM=yes-real-money in .env
  kill switch       the file safety.kill_switch (data/STOP) exists
  equity            equity <= 0, or it moved more than max_equity_change since the last cycle (bad marks)
  drawdown          equity below (1 - max_drawdown) of its high-water mark
  total loss        equity below (1 - max_total_loss) of everything deposited: the experiment is over
Routine budget (not an alarm: nothing is cancelled, entries simply wait):
  daily budget      at most max_orders_per_day orders and max_deploy_per_day_pct of equity opened in any 24 hours
Per-order checks (that market is skipped, the rest of the cycle runs):
  stale forecast    older than max_forecast_age_hours
  stale book        order book snapshot older than max_book_age_seconds
  moved             the mid moved more than max_move_since_forecast since the forecast (news the model has not seen)
  spread            wider than max_spread
  rules             the forecaster did not confirm that the resolution rules are clear
  too close         less than min_hours_to_resolution left
  order size        above max_order_usd, or above max_order_pct of equity
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

LIVE_CONFIRM_ENV = "PMT_LIVE_CONFIRM"
LIVE_CONFIRM_VALUE = "yes-real-money"
EXIT_CODE = 4

DEFAULTS = {
    "kill_switch": "data/STOP",
    "max_equity_change": 0.20,
    "max_drawdown": 0.15,
    "max_total_loss": 0.25,
    "max_orders_per_day": 6,
    "max_deploy_per_day_pct": 0.10,
    "max_forecast_age_hours": 6.0,
    "max_book_age_seconds": 120.0,
    "max_move_since_forecast": 0.04,
    "max_spread": 0.04,
    "min_hours_to_resolution": 24.0,
    "max_order_usd": 100.0,
    "max_order_pct": 0.04,
    "require_rules_clear": True,
}


class SafetyStop(RuntimeError):
    """A safety limit tripped: open nothing."""


def settings(cfg: dict | None) -> dict:
    out = dict(DEFAULTS)
    out.update((cfg or {}).get("safety") or {})
    return out


def is_live(cfg: dict | None) -> bool:
    return str(((cfg or {}).get("account") or {}).get("mode", "paper")).lower() == "live"


def live_confirmed() -> bool:
    return os.environ.get(LIVE_CONFIRM_ENV, "") == LIVE_CONFIRM_VALUE


def require_live_confirmation(cfg: dict | None) -> None:
    if is_live(cfg) and not live_confirmed():
        raise SafetyStop(f"account.mode is 'live' (real money) but {LIVE_CONFIRM_ENV} is not set to "
                         f"'{LIVE_CONFIRM_VALUE}' in .env: no orders sent")


@dataclass
class AccountCheck:
    ok: bool                     # no stop tripped
    exits_ok: bool               # selling existing positions allowed
    stops: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    orders_left: int = 0         # today's remaining budget, in orders ...
    usd_left: float = 0.0        # ... and in dollars
    stats: dict = field(default_factory=dict)

    @property
    def entries_ok(self) -> bool:
        return self.ok and self.orders_left > 0 and self.usd_left > 0

    def summary(self) -> str:
        s = self.stats
        head = (f"Safety: {'PASS' if self.ok else 'STOP'} | equity ${s.get('equity', 0):,.2f}"
                + (f" ({s['equity_change']:+.1%} vs last cycle)" if s.get("equity_change") is not None else "")
                + (f" | drawdown {s['drawdown']:.1%}" if s.get("drawdown") is not None else "")
                + f" | last 24h: {s.get('orders_24h', 0)} orders, ${s.get('deployed_24h', 0):,.2f}")
        return "\n".join([head] + [f"  STOP: {x}" for x in self.stops] + [f"  note: {x}" for x in self.notes])


def check_account(cfg: dict | None, equity: float, prev_equity: float | None, high_water: float | None,
                  deposited: float | None, orders_24h: int = 0, deployed_24h: float = 0.0,
                  root: Path | str = ".") -> AccountCheck:
    st = settings(cfg)
    res = AccountCheck(ok=True, exits_ok=True)
    res.stats.update(equity=float(equity or 0), orders_24h=orders_24h, deployed_24h=deployed_24h,
                     equity_change=None, drawdown=None)
    stops = res.stops

    if is_live(cfg) and not live_confirmed():
        stops.append(f"live account without {LIVE_CONFIRM_ENV}={LIVE_CONFIRM_VALUE}")
        res.exits_ok = False
    ks = Path(root) / st["kill_switch"] if st.get("kill_switch") else None
    if ks is not None and ks.exists():
        stops.append(f"kill switch {st['kill_switch']} exists: delete it to trade again")
        res.exits_ok = False

    if not equity or equity <= 0 or equity != equity:
        stops.append(f"account equity is {equity!r}")
        res.ok = False
        return res
    if prev_equity:
        chg = equity / prev_equity - 1
        res.stats["equity_change"] = chg
        if abs(chg) > st["max_equity_change"]:
            stops.append(f"equity ${equity:,.2f} is {chg:+.1%} vs the last cycle's ${prev_equity:,.2f} "
                         f"(limit {st['max_equity_change']:.0%}): check the marks before trading")
    if high_water and high_water > 0:
        dd = 1 - equity / high_water
        res.stats["drawdown"] = dd
        if dd > st["max_drawdown"]:
            stops.append(f"drawdown {dd:.1%} from the high-water mark ${high_water:,.2f} exceeds {st['max_drawdown']:.0%}: "
                         "no new positions until reviewed")
    if deposited and deposited > 0 and equity < (1 - st["max_total_loss"]) * deposited:
        stops.append(f"equity ${equity:,.2f} is more than {st['max_total_loss']:.0%} below the ${deposited:,.2f} deposited: "
                     "experiment stop")
    res.orders_left = max(int(st["max_orders_per_day"]) - int(orders_24h), 0)
    res.usd_left = max(st["max_deploy_per_day_pct"] * equity - deployed_24h, 0.0)
    if res.orders_left <= 0:
        res.notes.append(f"daily budget used: {orders_24h} orders in the last 24 hours (limit {st['max_orders_per_day']})")
    elif res.usd_left <= 0:
        res.notes.append(f"daily budget used: ${deployed_24h:,.2f} opened in the last 24 hours "
                         f"(limit {st['max_deploy_per_day_pct']:.0%} of equity)")
    res.ok = not stops
    return res


def check_order(cfg: dict | None, *, usd: float, equity: float, forecast_ts: float, forecast_mid: float | None,
                mid_now: float | None, spread: float | None, book_ts: float, rules_clear: bool | None,
                hours_to_resolution: float | None, now: float | None = None) -> list[str]:
    """Reasons this order must not be sent (empty list = fine)."""
    st = settings(cfg)
    now = now or time.time()
    why: list[str] = []
    age_h = (now - forecast_ts) / 3600.0
    if age_h > st["max_forecast_age_hours"]:
        why.append(f"forecast is {age_h:.1f} h old (limit {st['max_forecast_age_hours']:g} h)")
    if now - book_ts > st["max_book_age_seconds"]:
        why.append(f"order book snapshot is {now - book_ts:.0f} s old (limit {st['max_book_age_seconds']:g} s)")
    if mid_now is None or spread is None:
        why.append("no two-sided market")
    else:
        if spread > st["max_spread"] + 1e-9:
            why.append(f"spread {spread:.3f} wider than {st['max_spread']:.3f}")
        if forecast_mid is not None and abs(mid_now - forecast_mid) > st["max_move_since_forecast"] + 1e-9:
            why.append(f"mid moved {mid_now - forecast_mid:+.3f} since the forecast "
                       f"(limit {st['max_move_since_forecast']:.3f}): re-forecast first")
    if st["require_rules_clear"] and not rules_clear:
        why.append("resolution rules not confirmed clear by the forecaster")
    if hours_to_resolution is not None and hours_to_resolution < st["min_hours_to_resolution"]:
        why.append(f"{hours_to_resolution:.1f} h to resolution (minimum {st['min_hours_to_resolution']:g} h)")
    if usd > st["max_order_usd"] + 1e-9:
        why.append(f"order ${usd:,.2f} above the ${st['max_order_usd']:,.2f} ceiling")
    if equity > 0 and usd > st["max_order_pct"] * equity + 1e-9:
        why.append(f"order ${usd:,.2f} above {st['max_order_pct']:.0%} of equity")
    return why
