"""Run every rule of every family on the current panel and write one results table.

    python research/run_sweep.py --round r01                      all categories downloaded so far
    python research/run_sweep.py --round r01 --categories Economics,Politics

Writes research/results/<round>.csv (aggregated statistics only, safe to commit) and prints the rules that pass
the promotion test, the strongest leads and the reliably losing rules.
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import panel  # noqa: E402
from backtest import Panel, row, verdict  # noqa: E402
from families import Features, all_rules, persistence  # noqa: E402


def titles_for(df: pd.DataFrame, db_path) -> np.ndarray:
    db = sqlite3.connect(str(db_path), timeout=60)
    t = pd.read_sql_query("SELECT ticker, title FROM markets WHERE candles_done=1", db)
    db.close()
    return df[["ticker"]].merge(t, on="ticker", how="left")["title"].to_numpy(object)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--db", default=str(panel.DB))
    ap.add_argument("--categories", default="")
    ap.add_argument("--min-events", type=int, default=100)
    ap.add_argument("--split", default="", help="in/out-of-sample boundary (default 2026-04-01)")
    args = ap.parse_args()
    cats = [c.strip() for c in args.categories.split(",") if c.strip()] or None
    t0 = time.time()
    if args.split:
        panel.set_split(args.split)
    df = panel.load(args.db, cats)
    print(panel.describe(df))
    if df.empty:
        return 1
    p = Panel(df)
    f = Features(p)
    rows = []
    for family, name, mask, side, entry in all_rules(f, titles_for(df, args.db)):
        ins, oos = p.evaluate(mask, side, entry)
        extra = {"fill": p.fill_rate(mask, side)} if entry == "mk" else {"fill": 1.0}
        r = row(family, name, side, entry, ins, oos, **extra)
        r["verdict"] = verdict(r, args.min_events)
        rows.append(r)
    for family, name, mask, side, entry, n_series in persistence(f):
        ins, oos = p.evaluate(mask, side, entry)
        r = row(family, f"{name} ({n_series} series)", side, entry, ins, oos, fill=float("nan"))
        # selected on the in-sample half, so only the out-of-sample half counts
        r["verdict"] = ("thin" if oos.events < args.min_events else "pass" if oos.ret > 0 and oos.t >= 3 else
                        "lead" if oos.ret > 0 and oos.t >= 2 else "no")
        rows.append(r)
    out = pd.DataFrame(rows)
    (HERE / "results").mkdir(exist_ok=True)
    path = HERE / "results" / f"{args.round}.csv"
    out.round(5).to_csv(path, index=False)
    print(f"\n{len(out)} rules in {time.time() - t0:.0f} s -> {path}")
    print("verdicts:", out["verdict"].value_counts().to_dict())
    show = ["family", "rule", "side", "entry", "is_events", "is_ret", "is_t", "is_evret", "oos_events", "oos_ret", "oos_t",
            "oos_evret", "oos_evt", "oos_win", "oos_cost", "fill"]
    pd.set_option("display.width", 250, "display.max_colwidth", 70, "display.max_rows", 200)
    for v, title in (("pass", "PASS (both halves positive, out-of-sample t >= 3)"), ("lead", "LEADS (out-of-sample t >= 2)"),
                     ("loses", "RELIABLY LOSING")):
        sel = out[out["verdict"] == v].sort_values("oos_t", ascending=(v == "loses"))
        print(f"\n{title}: {len(sel)}")
        if len(sel):
            print(sel[show].head(40).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
