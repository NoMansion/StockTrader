"""Keep the paper bot cycling: run a cycle whenever the last one started more than --every hours ago, then export
the forecast log. Safe to kill and restart at any time: the schedule lives in the ledger, not in this process.

    python scripts/paper_loop.py --config data/cloud_config.yaml --every 3
"""
import argparse
import sqlite3
import subprocess
import sys
import time

from _bootstrap import ROOT


def last_run_started(db_path) -> float:
    try:
        db = sqlite3.connect(str(db_path), timeout=30)
        row = db.execute("SELECT MAX(started) FROM runs").fetchone()
        db.close()
        return float(row[0] or 0.0)
    except sqlite3.Error:
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--every", type=float, default=3.0, help="hours between cycles")
    ap.add_argument("--poll", type=float, default=300.0, help="seconds between checks")
    args = ap.parse_args()
    db = ROOT / "data" / "pmt.db"
    cycle = [sys.executable, str(ROOT / "scripts" / "run_cycle.py")] + (["--config", args.config] if args.config else [])
    while True:
        if time.time() - last_run_started(db) >= args.every * 3600:
            print(time.strftime("===== %Y-%m-%d %H:%M:%S UTC", time.gmtime()), flush=True)
            subprocess.run(cycle, cwd=str(ROOT))
            subprocess.run([sys.executable, str(ROOT / "scripts" / "export_forecasts.py")], cwd=str(ROOT))
        time.sleep(args.poll)


if __name__ == "__main__":
    sys.exit(main())
