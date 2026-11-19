"""Live-vs-model tracking: how much the paper (or real) account's daily return differs from what the
model's own decisions would have earned under the backtest's execution assumptions.

Each real run_daily saves one snapshot, data/targets/<decision date>.json:
    holdings  the account's actual weights at the decision (before any order), fractions of equity
    targets   the final target weights (stocks + sleeve ETFs) the orders aim for
    skip      names left inside the no-trade band (not traded)

For the trading day t after a decision on day d, the model return starts from the ACTUAL holdings of d, so each
day's gap is that day's execution only (no drift builds up):
    overnight   holdings earn adj_open(t) / adj_close(d) - 1
    at the open the book moves to the targets (skip names keep their drifted weight), paying cost_bps per side
                on the traded weight (the backtest's next-open fill at 10 bps)
    intraday    the new book earns adj_close(t) / adj_open(t) - 1; cash earns nothing
The gap (actual - model) then holds fill prices vs the open, fractional orders filled after the open, orders that
did not fill, whole-share rounding, and cash interest/fees the model ignores.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

TARGETS_DIR = Path("data/targets")


def save_snapshot(day, holdings: pd.Series, targets: pd.Series, skip, equity: float,
                  out_dir: Path = TARGETS_DIR, source: str = "run_daily") -> Path:
    """Write one decision snapshot (weights as fractions of equity). Returns the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    clean = lambda s: {str(k): round(float(v), 8) for k, v in s.items() if abs(float(v)) > 1e-10}
    d = {"date": str(pd.Timestamp(day).date()), "source": source, "equity": round(float(equity), 2),
         "holdings": clean(holdings), "targets": clean(targets), "skip": sorted(str(x) for x in skip)}
    p = out_dir / f"{d['date']}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(p)
    return p


def load_snapshots(out_dir: Path = TARGETS_DIR) -> dict[pd.Timestamp, dict]:
    snaps = {}
    for p in sorted(out_dir.glob("*.json")):
        d = json.loads(p.read_text())
        d["holdings"] = pd.Series(d["holdings"], dtype="float64")
        d["targets"] = pd.Series(d["targets"], dtype="float64")
        d["skip"] = set(d.get("skip", []))
        snaps[pd.Timestamp(d["date"])] = d
    return snaps


def model_day(holdings: pd.Series, targets: pd.Series, skip: set, prev_close: pd.Series, open_: pd.Series,
              close: pd.Series, cost_bps: float = 10.0) -> dict:
    """One day of the model (see module docstring). Prices are total-return adjusted, indexed by ticker.
    A name with no price that day keeps its value (return 0) and is reported in `missing`."""
    names = holdings.index.union(targets.index)
    missing = sorted(t for t in names if not (pd.notna(prev_close.get(t)) and pd.notna(open_.get(t)) and pd.notna(close.get(t))))
    g = (open_.reindex(names) / prev_close.reindex(names) - 1).fillna(0.0)
    h = (close.reindex(names) / open_.reindex(names) - 1).fillna(0.0)
    hw = holdings.reindex(names).fillna(0.0)
    v_open = 1.0 + float((hw * g).sum())
    drift = hw * (1 + g) / v_open                          # weights at the open, before trading
    w = targets.reindex(names).fillna(0.0).copy()
    keep = [t for t in skip if t in names]
    w.loc[keep] = drift.loc[keep]                          # inside the band: not traded
    turnover = float((w - drift).abs().sum())
    cost = turnover * cost_bps / 1e4
    ret = v_open * (1 - cost) * (1 + float((w * h).sum())) - 1
    return {"model_ret": ret, "overnight": v_open - 1, "intraday": float((w * h).sum()), "turnover": turnover,
            "cost": cost, "missing": missing}


def track(snaps: dict, adj_open: pd.DataFrame, adj_close: pd.DataFrame, actual: pd.Series,
          cost_bps: float = 10.0) -> pd.DataFrame:
    """Day-by-day actual vs model. `actual` = the account's daily return indexed by date; adj_open / adj_close are
    wide (date x ticker). Each snapshot is matched to the next trading day in adj_close's index."""
    days = adj_close.index
    rows = []
    for d, s in sorted(snaps.items()):
        nxt = days[days > d]
        if len(nxt) == 0 or d not in days:
            continue
        t = nxt[0]
        m = model_day(s["holdings"], s["targets"], s["skip"], adj_close.loc[d], adj_open.loc[t], adj_close.loc[t], cost_bps)
        a = actual.get(t)
        rows.append({"decision": d.date(), "date": t.date(), "actual_ret": a, "model_ret": m["model_ret"],
                     "gap_bps": (a - m["model_ret"]) * 1e4 if a is not None and pd.notna(a) else None,
                     "turnover": m["turnover"], "model_cost_bps": m["cost"] * 1e4,
                     "stocks_target": float(s["targets"].drop([x for x in ("IEF", "GLD") if x in s["targets"].index]).sum()),
                     "missing": ",".join(m["missing"])})
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> dict:
    g = df["gap_bps"].dropna()
    if g.empty:
        return {"days": 0}
    a = df.loc[g.index, "actual_ret"]; m = df.loc[g.index, "model_ret"]
    return {"days": int(len(g)), "mean_gap_bps": float(g.mean()), "median_gap_bps": float(g.median()),
            "worst_gap_bps": float(g.min()), "best_gap_bps": float(g.max()),
            "actual_total": float((1 + a).prod() - 1), "model_total": float((1 + m).prod() - 1),
            "tracking_error_ann": float((a - m).std() * (252 ** 0.5)) if len(g) > 1 else None,
            "mean_turnover": float(df.loc[g.index, "turnover"].mean())}
