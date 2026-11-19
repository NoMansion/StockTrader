"""Where to rest the NO bid, and for how long: the one setting of the longshot rule that a trader actually chooses.

    python research/resting_variants.py --sample liquid --min-cumvol 5150 --categories "Economics,Politics,Science and Technology"

The sweeps rest the order at the best NO bid (one minus the YES ask) for three daily bars. This varies both:

  deeper    cents below the best NO bid. 0 = join the best bid; 1 = a cent cheaper, filled only if YES trades a cent
            higher; -1 = a cent BETTER than the best bid (inside the spread, where the spread allows it)
  window    daily bars the order is left working (1, 3, 7)

A fill needs the market to trade THROUGH the order's price (the YES bid reaching it, or a print beyond it): never a
touch. For each variant: fills, mean return after fees, losing events against break-even (the tail test), and the
account replay at 1% stakes, before and after the sample split.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import panel  # noqa: E402
import portfolio  # noqa: E402
from analyze_rule import tail  # noqa: E402
from backtest import Panel  # noqa: E402
from families import Features  # noqa: E402


def variant(p: Panel, mask: np.ndarray, deeper: float, window: int) -> pd.DataFrame:
    d = p.df
    g = d.groupby("ticker", sort=False)
    hi = pd.concat([g["bid_hi"].shift(-i) for i in range(1, window + 1)], axis=1).max(axis=1).to_numpy()
    phi = pd.concat([g["px_hi"].shift(-i) for i in range(1, window + 1)], axis=1).max(axis=1).to_numpy()
    level = d["ask"].to_numpy("float64") + deeper                       # the YES price our NO bid sits at
    ok = mask & (level > d["bid"].to_numpy("float64") + 1e-6) & (level < 0.995)     # must stay off the other side
    filled = ok & ((hi >= level - 1e-6) | (phi > level + 1e-6))
    cost = (1 - level) + np.where(d["maker_fee"], panel.MAKER, 0.0) * d["mult"].to_numpy() * level * (1 - level)
    r = ((1 - d["y"].to_numpy()) - cost) / cost
    rows = p.first_per_market(filled)
    placed = p.first_per_market(ok)
    out = pd.DataFrame({"ts": d["ts"].to_numpy()[rows], "close": d["close_ts"].to_numpy()[rows], "r": r[rows],
                        "event": p.event[rows], "oos": p.oos[rows], "cost": cost[rows]})
    out.attrs["fill_rate"] = float(filled[placed].mean()) if placed.size else float("nan")
    return out


def describe(b: pd.DataFrame) -> dict:
    out = {"bets": len(b), "events": b["event"].nunique(), "fill": b.attrs.get("fill_rate", np.nan),
           "price": b["cost"].mean(), "mean": b["r"].mean()}
    for label, part in (("in", b[~b["oos"]]), ("out", b[b["oos"]])):
        if part.empty:
            continue
        t = tail(part.groupby("event")["r"].sum().to_numpy())
        bets = part[["ts", "close", "r", "event"]].sort_values("ts").to_numpy("float64")
        bets[:, 1] = np.maximum(bets[:, 1], bets[:, 0] + 86400)
        a = portfolio.simulate(bets, stake_frac=0.01)
        out.update({f"{label}_mean": part["r"].mean(), f"{label}_lost": f"{t['losing']}/{t['events']}",
                    f"{label}_tail": "ok" if t["proven"] else "no", f"{label}_cagr": a.cagr, f"{label}_dd": a.max_dd})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(panel.DB))
    ap.add_argument("--categories", default="")
    ap.add_argument("--sample", default="liquid", choices=["random", "liquid"])
    ap.add_argument("--min-cumvol", type=float, default=None)
    ap.add_argument("--max-mid", type=float, default=0.05)
    ap.add_argument("--max-days", type=float, default=30)
    ap.add_argument("--max-spread", type=float, default=0.05)
    args = ap.parse_args()
    cats = [c.strip() for c in args.categories.split(",") if c.strip()] or None
    df = panel.load(args.db, cats, sample=args.sample, min_cumvol=args.min_cumvol)
    print(panel.describe(df))
    if df.empty:
        return 1
    p = Panel(df)
    f = Features(p)
    mask = f.base & (f.mid > 0) & (f.mid <= args.max_mid) & (f.dte <= args.max_days) & (f.spread <= args.max_spread)
    rows = []
    for deeper in (-0.01, 0.0, 0.01, 0.02, 0.03):
        for window in (1, 3, 7):
            b = variant(p, mask, deeper, window)
            if len(b):
                rows.append({"deeper_c": round(deeper * 100), "window": window, **describe(b)})
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    fmt = {c: "{:+.2%}".format for c in ("mean", "in_mean", "out_mean", "in_cagr", "out_cagr")}
    fmt.update({"fill": "{:.0%}".format, "price": "{:.3f}".format, "in_dd": "{:.1%}".format, "out_dd": "{:.1%}".format})
    print(f"\nNO where YES mid <= {args.max_mid * 100:g}c, <= {args.max_days:g}d, spread <= {args.max_spread * 100:g}c; resting NO bid")
    print(out.to_string(index=False, formatters=fmt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
