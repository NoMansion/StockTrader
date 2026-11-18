"""Write the forecast record to a small CSV that can be committed: one row per forecast, with the market price at
that moment, what the rules decided, and the outcome once known. The ledger itself (data/pmt.db) is not committed;
this file is the durable copy of the experiment's main result.

    python scripts/export_forecasts.py                 -> reports/forward_log.csv
"""
import argparse
import csv
import json
import sys
import time

from _bootstrap import ROOT

from src.ledger import Ledger


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "pmt.db"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "forward_log.csv"))
    args = ap.parse_args()
    led = Ledger(args.db)
    rows = led.q("""SELECT f.id, f.ts, f.market_id, m.question, m.category, m.event_id, m.end_ts, f.model, f.p_yes, f.p_runs,
                           f.confidence, f.rules_clear, f.flags, f.market_mid, m.payout_yes,
                           (SELECT action FROM decisions d WHERE d.forecast_id = f.id ORDER BY d.id DESC LIMIT 1) AS action,
                           (SELECT reason FROM decisions d WHERE d.forecast_id = f.id ORDER BY d.id DESC LIMIT 1) AS reason
                    FROM forecasts f JOIN markets m ON m.market_id = f.market_id ORDER BY f.ts""")
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else ""
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["forecast_utc", "market", "question", "category", "event", "closes_utc", "model", "p_yes", "runs", "confidence",
                    "rules_clear", "flags", "market_mid", "gap", "decision", "reason", "resolved_yes"])
        for r in rows:
            gap = "" if r["market_mid"] is None else round(r["p_yes"] - r["market_mid"], 4)
            w.writerow([iso(r["ts"]), r["market_id"], (r["question"] or "")[:160], r["category"], r["event_id"], iso(r["end_ts"]),
                        r["model"], r["p_yes"], " ".join(str(x) for x in json.loads(r["p_runs"] or "[]")), r["confidence"],
                        r["rules_clear"], len(json.loads(r["flags"] or "[]")), r["market_mid"], gap, r["action"] or "",
                        (r["reason"] or "")[:140], "" if r["payout_yes"] is None else r["payout_yes"]])
    led.close()
    print(f"{len(rows)} forecasts -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
