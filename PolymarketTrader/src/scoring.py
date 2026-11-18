"""Scoring: is the forecaster better than the market price it is betting against?

Three measures, in the order they become informative:

  1. Price movement after the forecast ("closing-line value"). For every forecast, did the market later move
     toward the model's number or away from it? Needs no resolutions, so it is the first signal available.
  2. Brier score against the market. On resolved markets, compare (model - outcome)^2 with (market - outcome)^2,
     both taken at the time of the forecast. The paired difference has a standard error, so skill can be told
     from luck with far fewer bets than P&L needs.
  3. P&L. The noisiest of the three: a handful of binary payoffs dominates it for months.

One row per market (its first forecast) is used for the significance test, because repeat forecasts of the same
market are not independent observations.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .ledger import Ledger


def brier(p: float, outcome: float) -> float:
    return (p - outcome) ** 2


def log_loss(p: float, outcome: float, eps: float = 1e-4) -> float:
    p = min(max(p, eps), 1 - eps)
    return -(outcome * math.log(p) + (1 - outcome) * math.log(1 - p))


def mean_se(xs: list[float]) -> tuple[float, float]:
    """Mean and its standard error."""
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan")
    m = sum(xs) / n
    if n < 2:
        return m, float("nan")
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m, math.sqrt(var / n)


@dataclass
class BrierReport:
    n: int = 0
    model: float = float("nan")
    market: float = float("nan")
    blend: float = float("nan")          # the shrunk probability actually traded on
    edge: float = float("nan")           # market Brier minus model Brier (positive = model better)
    edge_se: float = float("nan")
    t: float = float("nan")
    calibration: list[dict] = field(default_factory=list)

    def verdict(self) -> str:
        if self.n < 30:
            return f"too few resolved markets to say anything ({self.n}; need 30 for a first look, 100+ to conclude)"
        if self.t != self.t:
            return "no variation yet"
        if self.t >= 2.0:
            return f"model beats the market price (t = {self.t:.1f})"
        if self.t <= -2.0:
            return f"model is WORSE than the market price (t = {self.t:.1f}): stop trading on it"
        return f"no measurable difference from the market price yet (t = {self.t:.1f})"


def brier_vs_market(ledger: Ledger, shrink_weight: float = 0.5, first_only: bool = True) -> BrierReport:
    """Resolved markets only (payout 0 or 1; 50/50 resolutions are left out)."""
    rows = ledger.q("""SELECT f.market_id, f.ts, f.p_yes, f.market_mid, m.payout_yes FROM forecasts f
                       JOIN markets m ON m.market_id = f.market_id
                       WHERE m.payout_yes IN (0, 1) AND f.market_mid IS NOT NULL ORDER BY f.ts""")
    seen, model, market, blend, diff = set(), [], [], [], []
    buckets: dict[int, list[tuple[float, float]]] = {}
    for r in rows:
        if first_only and r["market_id"] in seen:
            continue
        seen.add(r["market_id"])
        p, mkt, o = float(r["p_yes"]), float(r["market_mid"]), float(r["payout_yes"])
        b = mkt + shrink_weight * (p - mkt)
        model.append(brier(p, o)); market.append(brier(mkt, o)); blend.append(brier(b, o))
        diff.append(brier(mkt, o) - brier(p, o))
        buckets.setdefault(min(int(p * 5), 4), []).append((p, o))
    rep = BrierReport(n=len(model))
    if not model:
        return rep
    rep.model, rep.market, rep.blend = sum(model) / len(model), sum(market) / len(market), sum(blend) / len(blend)
    rep.edge, rep.edge_se = mean_se(diff)
    rep.t = rep.edge / rep.edge_se if rep.edge_se and rep.edge_se == rep.edge_se and rep.edge_se > 0 else float("nan")
    for k in sorted(buckets):
        ps, os_ = zip(*buckets[k])
        rep.calibration.append({"bucket": f"{k * 20}-{k * 20 + 20}%", "n": len(ps),
                                "mean_forecast": sum(ps) / len(ps), "resolved_yes": sum(os_) / len(os_)})
    return rep


@dataclass
class DriftReport:
    n: int = 0
    mean_capture: float = float("nan")   # average move toward the model, as a fraction of the initial gap
    capture_se: float = float("nan")
    toward: int = 0                      # forecasts the market later moved toward
    away: int = 0
    horizon_hours: float = 0.0


def price_drift(ledger: Ledger, horizon_hours: float = 72.0, min_gap: float = 0.03) -> DriftReport:
    """For forecasts that disagreed with the market by at least `min_gap`: how much of the gap did the market close
    within `horizon_hours`? +1 = the price moved all the way to the model's number, 0 = it did not move, negative
    = it moved the other way. A resolved market counts at its payout."""
    rep = DriftReport(horizon_hours=horizon_hours)
    caps = []
    for f in ledger.q("SELECT f.*, m.payout_yes, m.resolved_ts FROM forecasts f JOIN markets m ON m.market_id=f.market_id "
                      "WHERE f.market_mid IS NOT NULL"):
        gap = float(f["p_yes"]) - float(f["market_mid"])
        if abs(gap) < min_gap:
            continue
        t1 = float(f["ts"]) + horizon_hours * 3600.0
        later = None
        if f["payout_yes"] is not None and f["resolved_ts"] is not None and float(f["resolved_ts"]) <= t1:
            later = float(f["payout_yes"])
        else:
            snap = ledger.one("SELECT mid, ts FROM snapshots WHERE market_id=? AND ts>=? AND mid IS NOT NULL ORDER BY ts LIMIT 1",
                              (f["market_id"], t1))
            later = float(snap["mid"]) if snap else None
        if later is None:
            continue
        cap = (later - float(f["market_mid"])) / gap
        caps.append(max(-3.0, min(3.0, cap)))
        rep.toward += cap > 0
        rep.away += cap < 0
    rep.n = len(caps)
    if caps:
        rep.mean_capture, rep.capture_se = mean_se(caps)
    return rep


def pnl(ledger: Ledger) -> dict:
    """Realised and open P&L from the ledger. Open positions are valued at the last recorded equity row."""
    dep = ledger.deposits()
    eq = ledger.last_equity()
    equity = float(eq["equity"]) if eq else ledger.cash()
    fees = ledger.one("SELECT COALESCE(SUM(fee), 0) AS f FROM fills")["f"]
    n_buys = ledger.one("SELECT COUNT(DISTINCT market_id) AS n FROM fills WHERE side='BUY'")["n"]
    settled = ledger.q("""SELECT f.market_id,
                                 SUM(CASE WHEN f.side='BUY' THEN -(f.price*f.shares + f.fee) ELSE f.price*f.shares - f.fee END) AS net
                          FROM fills f JOIN markets m ON m.market_id=f.market_id
                          WHERE m.payout_yes IS NOT NULL GROUP BY f.market_id""")
    wins = sum(1 for r in settled if r["net"] > 0)
    hw = ledger.high_water()
    return {"deposited": dep, "equity": equity, "pnl": equity - dep, "return": (equity / dep - 1) if dep else 0.0,
            "fees": float(fees), "markets_traded": int(n_buys), "markets_settled": len(settled), "settled_wins": wins,
            "settled_pnl": sum(float(r["net"]) for r in settled),
            "drawdown": (1 - equity / hw) if hw else 0.0}


def bets_needed(edge: float, p: float = 0.5, z: float = 2.0) -> int:
    """Independent bets needed before an average edge of `edge` (probability points) shows up as a win rate
    `z` standard errors above break-even, for contracts priced near `p`. At a 5-point edge on 50-cent contracts
    that is 400 bets, which is why P&L alone cannot validate this strategy in a few months."""
    if edge <= 0:
        return 10 ** 9
    return int(math.ceil(z * z * p * (1 - p) / (edge * edge)))


# ---- go-live gates -----------------------------------------------------------------------------
# Written down before the first forecast so they cannot be moved afterwards (docs/GO_LIVE.md explains each).
GATES = {
    "min_weeks": 8,                 # of forward paper trading
    "min_resolved_events": 150,     # forecasts on distinct events that have resolved
    "min_drift_obs": 200,           # forecasts with a 72-hour price-movement observation
    "min_drift_t": 2.0,             # the market must move toward the model, clearly
    "min_brier_t": -2.0,            # the model must not be significantly worse than the price
    "min_paper_pnl": 0.0,           # after fees and pessimistic fills
}


def gates(ledger: Ledger, shrink_weight: float = 0.5) -> list[tuple[str, bool, str]]:
    """Each go-live gate as (name, passed, where it stands). All must pass; none can be waived by the bot."""
    first = ledger.one("SELECT MIN(ts) AS t FROM forecasts")["t"]
    last = ledger.one("SELECT MAX(ts) AS t FROM forecasts")["t"]
    weeks = ((last - first) / (7 * 86400.0)) if first and last else 0.0
    events = ledger.one("""SELECT COUNT(DISTINCT COALESCE(m.event_id, m.market_id)) AS n FROM forecasts f
                           JOIN markets m ON m.market_id=f.market_id WHERE m.payout_yes IN (0, 1)""")["n"]
    b = brier_vs_market(ledger, shrink_weight)
    d = price_drift(ledger)
    d_t = d.mean_capture / d.capture_se if d.n > 1 and d.capture_se and d.capture_se > 0 else float("nan")
    p = pnl(ledger)
    def ok_t(t, lo, n):                    # a t-statistic on a handful of observations proves nothing
        return n >= 30 and t == t and t >= lo

    return [
        ("paper weeks", weeks >= GATES["min_weeks"], f"{weeks:.1f} of {GATES['min_weeks']}"),
        ("resolved events", events >= GATES["min_resolved_events"], f"{events} of {GATES['min_resolved_events']}"),
        ("price-movement observations", d.n >= GATES["min_drift_obs"], f"{d.n} of {GATES['min_drift_obs']}"),
        ("market moves toward the model", ok_t(d_t, GATES["min_drift_t"], d.n),
         f"t = {d_t:.1f} on {d.n} forecasts, needs {GATES['min_drift_t']:g} on 30+" if d_t == d_t else "no data"),
        ("not worse than the market price", ok_t(b.t, GATES["min_brier_t"], b.n),
         f"t = {b.t:.1f} on {b.n} markets, needs above {GATES['min_brier_t']:g} on 30+" if b.t == b.t else "no data"),
        ("paper profit after costs", p["markets_settled"] > 0 and p["pnl"] >= GATES["min_paper_pnl"], f"{p['pnl']:+,.2f}"),
    ]
