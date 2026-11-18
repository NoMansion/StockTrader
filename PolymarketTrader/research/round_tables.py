"""Markdown tables from a round's results file, for pasting into the report.

    python research/round_tables.py r07_liquid_economics            verdict counts, calibration, passes, leads, losers
    python research/round_tables.py r07_liquid_economics --family "25 longshot NO" --min-events 60
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def pct(x):
    return "" if pd.isna(x) else f"{x * 100:+.1f}%".replace("-", "−")


def tt(x):
    return "" if pd.isna(x) else f"{x:.1f}".replace("-", "−")


def table(d: pd.DataFrame, with_family: bool = True) -> str:
    head = (["Family"] if with_family else []) + ["Rule", "Side", "Entry", "In sample", "t", "Out of sample", "t", "t by event",
                                                  "Win rate out", "Events in / out", "Fill rate"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in d.itertuples():
        cells = ([r.family] if with_family else []) + [
            r.rule, r.side.upper(), "taker" if r.entry == "tk" else "resting" if r.entry == "mk" else r.entry,
            pct(r.is_ret), tt(r.is_t), pct(r.oos_ret), tt(r.oos_t), tt(r.oos_evt), f"{r.oos_win:.1%}",
            f"{int(r.is_events)} / {int(r.oos_events)}", "" if r.entry != "mk" or pd.isna(r.fill) else f"{r.fill:.0%}"]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines)


def calibration(d: pd.DataFrame) -> str:
    """One line per price band: what each side earned, taker and resting, in and out of sample."""
    c = d[d["family"] == "1 calibration"]
    if c.empty:
        return ""
    lines = ["| YES price | YES taker in / out | NO taker in / out | YES resting in / out | NO resting in / out | Events in / out |",
             "|---|---|---|---|---|---|"]
    for rule in c["rule"].drop_duplicates():
        cells = [rule.replace("mid ", "")]
        ev = ""
        for side, entry in (("yes", "tk"), ("no", "tk"), ("yes", "mk"), ("no", "mk")):
            r = c[(c["rule"] == rule) & (c["side"] == side) & (c["entry"] == entry)]
            if r.empty:
                cells.append("")
                continue
            r = r.iloc[0]
            cells.append(f"{pct(r.is_ret)} / {pct(r.oos_ret)}")
            if (side, entry) == ("yes", "tk"):
                ev = f"{int(r.is_events)} / {int(r.oos_events)}"
        lines.append("| " + " | ".join(cells + [ev]) + " |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("round")
    ap.add_argument("--family", default="")
    ap.add_argument("--min-events", type=int, default=100)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()
    d = pd.read_csv(HERE / "results" / f"{args.round}.csv")
    if args.family:
        f = d[(d["family"] == args.family) & (d["is_events"] >= args.min_events) & (d["oos_events"] >= args.min_events)]
        print(table(f.sort_values("oos_t", ascending=False), with_family=False))
        return 0
    print(f"{len(d)} rules: " + ", ".join(f"{k} {v}" for k, v in d["verdict"].value_counts().items()), "\n")
    print(calibration(d), "\n")
    for v, asc in (("pass", False), ("lead", False), ("loses", True)):
        sel = d[d["verdict"] == v].sort_values("oos_t", ascending=asc)
        print(f"**{v}: {len(sel)}**\n")
        if len(sel):
            print(table(sel.head(args.top)), "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
