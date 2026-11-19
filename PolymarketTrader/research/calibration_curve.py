"""How far the price is from the truth, band by band: the quoted mid against how often YES actually happened.

    python research/calibration_curve.py --sample liquid --min-cumvol 45000 --categories Economics,Politics

One observation per market per band: the first tradable bar at which the mid was in the band. `gap` is outcome
minus mid (negative: YES was priced too high); its standard error is clustered by event. `ev_gap` is the same
with each event counted once, however many markets it has: an event with thirty longshot outcomes otherwise
counts thirty times. Fees and spreads play
no part here: this is about the level of the price, not about what a trade would have earned.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import panel  # noqa: E402
from backtest import Panel  # noqa: E402
from families import PRICE, Features  # noqa: E402


def curve(p: Panel, f: Features, bands=PRICE) -> pd.DataFrame:
    mid = p.col("mid").astype("float64")
    rows = []
    for lo, hi in bands:
        idx = p.first_per_market(f.base & f.price(lo, hi))
        for label, part in (("in", idx[~p.oos[idx]]), ("out", idx[p.oos[idx]])):
            if part.size == 0:
                continue
            d = pd.DataFrame({"event": p.event[part], "gap": p.y[part] - mid[part]})
            ev = d.groupby("event")["gap"].agg(["sum", "size"])
            k = len(ev)
            se = np.sqrt(((ev["sum"] - d["gap"].mean() * ev["size"]) ** 2).sum()) / len(d) * (np.sqrt(k / (k - 1)) if k > 1 else np.nan)
            per_event = ev["sum"] / ev["size"]              # each event counts once, however many markets it has
            ev_se = per_event.std(ddof=1) / np.sqrt(k) if k > 1 else np.nan
            rows.append({"band": f"{lo * 100:g}-{hi * 100:g}c", "half": label, "markets": len(d), "events": k,
                         "mean_mid": mid[part].mean(), "yes_rate": p.y[part].mean(), "gap": d["gap"].mean(),
                         "t": d["gap"].mean() / se if se and se > 0 else np.nan, "ev_gap": per_event.mean(),
                         "ev_t": per_event.mean() / ev_se if ev_se and ev_se > 0 else np.nan})
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(panel.DB))
    ap.add_argument("--categories", default="")
    ap.add_argument("--sample", default="random", choices=["random", "liquid"])
    ap.add_argument("--min-cumvol", type=float, default=None)
    args = ap.parse_args()
    cats = [c.strip() for c in args.categories.split(",") if c.strip()] or None
    df = panel.load(args.db, cats, sample=args.sample, min_cumvol=args.min_cumvol)
    print(panel.describe(df))
    if df.empty:
        return 1
    p = Panel(df)
    c = curve(p, Features(p))
    pd.set_option("display.width", 200)
    print(c.to_string(index=False, formatters={"mean_mid": "{:.3f}".format, "yes_rate": "{:.3f}".format,
                                               "gap": "{:+.3f}".format, "t": "{:+.1f}".format,
                                               "ev_gap": "{:+.3f}".format, "ev_t": "{:+.1f}".format}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
