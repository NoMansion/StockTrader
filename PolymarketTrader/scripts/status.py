"""Where the account and the forecasts stand. Reads data/pmt.db only: no network, no Claude.

    python scripts/status.py            print the report
    python scripts/status.py --write    also save it to data/status.md
"""
import argparse
import sys
import time

from _bootstrap import ROOT

from src import scoring
from src.config import load_config
from src.ledger import Ledger


def fmt_ts(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts))) if ts else "-"


def report(ledger: Ledger, cfg: dict) -> str:
    w = float((cfg.get("sizing") or {}).get("shrink_weight", 0.5))
    p = scoring.pnl(ledger)
    out = [f"# PolymarketTrader status, {time.strftime('%Y-%m-%d %H:%M')}", "",
           f"Mode: {(cfg.get('account') or {}).get('mode', 'paper')}", "",
           "## Account",
           f"- Equity ${p['equity']:,.2f} on ${p['deposited']:,.2f} deposited: {p['pnl']:+,.2f} ({p['return']:+.1%}), "
           f"drawdown from peak {p['drawdown']:.1%}",
           f"- Cash ${ledger.cash():,.2f}; fees paid ${p['fees']:,.2f}",
           f"- Markets traded {p['markets_traded']}, settled {p['markets_settled']} "
           f"({p['settled_wins']} profitable, net {p['settled_pnl']:+,.2f})", ""]

    pos = ledger.positions()
    out.append(f"## Open positions ({len(pos)})")
    for r in pos:
        m = ledger.market(r["market_id"])
        snap = ledger.last_snapshot(r["market_id"])
        f = ledger.latest_forecast(r["market_id"])
        mid = snap["mid"] if snap else None
        mark = None if mid is None else (mid if r["outcome"] == "YES" else 1 - mid)
        avg = r["cost"] / r["shares"] if r["shares"] else 0
        now_txt = "-" if mark is None else f"{mark:.3f}"
        model_txt = "-" if not f else f"{f['p_yes']:.2f}"
        title = (m["question"] if m else r["market_id"])[:90]
        out.append(f"- {r['outcome']} {r['shares']:g} @ {avg:.3f}, now {now_txt}, model P(yes) {model_txt}: {title}")
    rest = ledger.q("SELECT * FROM orders WHERE status='resting' ORDER BY ts")
    out += ["", f"## Resting orders ({len(rest)})"]
    for o in rest:
        out.append(f"- buy {o['outcome']} ${o['usd']:,.2f} @ {o['limit_price']:.3f} since {fmt_ts(o['ts'])}: {o['market_id']}")

    b = scoring.brier_vs_market(ledger, shrink_weight=w)
    d = scoring.price_drift(ledger)
    n_f = ledger.one("SELECT COUNT(*) AS n, COUNT(DISTINCT market_id) AS m FROM forecasts")
    out += ["", "## Is the forecaster better than the market price?",
            f"- {n_f['n']} forecasts on {n_f['m']} markets; {b.n} of those markets have resolved",
            f"- Verdict: {b.verdict()}"]
    if b.n:
        out.append(f"- Brier score (lower is better): model {b.model:.4f}, market {b.market:.4f}, blend traded {b.blend:.4f}; "
                   f"model advantage {b.edge:+.4f} +/- {b.edge_se:.4f}")
        for c in b.calibration:
            out.append(f"  - forecasts {c['bucket']}: {c['n']} markets, mean forecast {c['mean_forecast']:.2f}, "
                       f"resolved yes {c['resolved_yes']:.2f}")
    if d.n:
        out.append(f"- Price movement {d.horizon_hours:g} h after forecasts that disagreed with the market by 3+ points: "
                   f"{d.toward} moved toward the model, {d.away} away; average {d.mean_capture:+.2f} of the gap "
                   f"(+/- {d.capture_se:.2f}) on {d.n} forecasts")
    else:
        out.append("- No price-movement observations yet (needs forecasts at least 72 hours old)")

    gs = scoring.gates(ledger, shrink_weight=w)
    out += ["", f"## Go-live gates ({sum(1 for _, ok, _ in gs if ok)} of {len(gs)} passed; all are required)"]
    for name, ok, where in gs:
        out.append(f"- [{'x' if ok else ' '}] {name}: {where}")

    out += ["", "## Last 15 decisions"]
    for r in ledger.q("SELECT * FROM decisions ORDER BY ts DESC LIMIT 15"):
        out.append(f"- {fmt_ts(r['ts'])} {r['action']:8s} {r['market_id'][:40]}: {(r['reason'] or '')[:140]}")
    runs = ledger.q("SELECT * FROM runs ORDER BY started DESC LIMIT 5")
    out += ["", "## Last 5 cycles"]
    for r in runs:
        out.append(f"- {fmt_ts(r['started'])} {r['status']} ({r['run_id']})")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args.config)
    db = ROOT / "data" / "pmt.db"
    if not db.exists():
        print("no data/pmt.db yet: run scripts/run_cycle.py first")
        return 0
    ledger = Ledger(db)
    try:
        text = report(ledger, cfg)
    finally:
        ledger.close()
    print(text)
    if args.write:
        (ROOT / "data" / "status.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
