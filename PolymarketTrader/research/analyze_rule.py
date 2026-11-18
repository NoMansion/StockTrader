"""Take one rule from a sweep apart before believing it.

    python research/analyze_rule.py --sample liquid --min-cumvol 45000 --categories Economics,Politics \
        --rule "NO at mid <= 5c, <= 30d, spread <= 5c" --side no --entry tk

A mean and a t-statistic are the wrong tools for a bet that wins two cents 199 times and loses 97 cents once, so
this prints what they hide:

  by year          bets, events, mean return, losing bets: is the result one period?
  the tail         losing events against the break-even loss rate, with an exact (Clopper-Pearson) upper bound on
                   the true loss rate; "proven" only if even that bound is below break-even
  concentration    share of bets and of profit by series
  capacity         contracts traded on the entry day and dollars traded in the week before
  holding time     days from entry to settlement, and the return per year of capital that implies
  account replay   research/portfolio.py at three stake sizes
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import panel  # noqa: E402
import portfolio  # noqa: E402
from backtest import Panel  # noqa: E402
from families import Features, all_rules  # noqa: E402
from run_sweep import titles_for  # noqa: E402


def binom_cdf(k: int, n: int, p: float) -> float:
    if p <= 0:
        return 1.0
    if p >= 1:
        return 1.0 if k >= n else 0.0
    return float(sum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                              + i * math.log(p) + (n - i) * math.log(1 - p)) for i in range(k + 1)))


def loss_rate_upper(k: int, n: int, conf: float = 0.95) -> float:
    """Exact one-sided upper bound on a rate after k hits in n tries (Clopper-Pearson)."""
    if n == 0 or k >= n:
        return 1.0
    lo, hi = k / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if binom_cdf(k, n, mid) > 1 - conf:
            lo = mid
        else:
            hi = mid
    return hi


def tail(event_ret: np.ndarray) -> dict:
    """Event-level picture of a lopsided bet. event_ret: summed return of each event's bets."""
    n = len(event_ret)
    lose = event_ret < 0
    k = int(lose.sum())
    gain = float(event_ret[~lose].mean()) if n - k else 0.0
    loss = float(-event_ret[lose].mean()) if k else float("nan")
    out = {"events": n, "losing": k, "gain_per_winner": gain, "loss_per_loser": loss, "upper95": loss_rate_upper(k, n)}
    # with no loss seen, assume a loser costs the whole stake (return -1 per bet, one bet per event)
    out["breakeven"] = gain / (gain + (loss if k else 1.0)) if gain > 0 else 0.0
    out["proven"] = out["upper95"] < out["breakeven"]
    return out


def find_rule(f: Features, titles, name: str, side: str, entry: str):
    for family, rule, mask, s, e in all_rules(f, titles):
        if rule == name and s == side and e == entry:
            return family, mask
    raise SystemExit(f"no rule named {name!r} with side {side}, entry {entry}")


def bets_frame(p: Panel, mask: np.ndarray, side: str, entry: str) -> pd.DataFrame:
    key = (side, entry)
    rows = p.first_per_market(mask & p.ok[key])
    d = p.df.iloc[rows]
    nxt = p.df.groupby("ticker", sort=False)["vol"].shift(-1).to_numpy()[rows]
    return pd.DataFrame({
        "ticker": d["ticker"].to_numpy(), "event": d["event"].to_numpy(), "series": d["series"].to_numpy(),
        "category": d["category"].to_numpy(), "ts": d["ts"].to_numpy(), "close_ts": d["close_ts"].to_numpy(),
        "year": pd.to_datetime(d["close_ts"].to_numpy(), unit="s").year, "oos": d["oos"].to_numpy(),
        "r": p.r[key][rows].astype("float64"), "cost": p.px[key][rows].astype("float64"),
        "hold": np.maximum((d["close_ts"].to_numpy() - d["ts"].to_numpy()) / 86400.0, 0.5),
        "day_contracts": np.nan_to_num(nxt, nan=0.0), "dvol7": d["dvol7"].to_numpy("float64")})


def report(b: pd.DataFrame, p: Panel, mask: np.ndarray, side: str, entry: str) -> str:
    out = []
    w = out.append
    w(f"{len(b):,} bets in {b['event'].nunique():,} events; mean return {b['r'].mean():+.2%} per bet, "
      f"mean price paid {b['cost'].mean():.3f}, losing bets {int((b['r'] < 0).sum()):,}")
    w("\nby year of close")
    g = b.groupby("year")
    t = pd.DataFrame({"bets": g.size(), "events": g["event"].nunique(), "mean_ret": g["r"].mean(),
                      "losing_bets": g["r"].apply(lambda x: int((x < 0).sum())), "worst": g["r"].min()})
    w(t.to_string(float_format=lambda x: f"{x:+.3f}"))
    w("\nthe tail (events: the sum of each event's bets)")
    for label, part in (("in sample", b[~b["oos"]]), ("out of sample", b[b["oos"]]), ("all", b)):
        if part.empty:
            continue
        x = tail(part.groupby("event")["r"].sum().to_numpy())
        w(f"  {label:14s} {x['events']:5d} events, {x['losing']:3d} losing ({x['losing'] / x['events']:.2%}); a winner makes "
          f"{x['gain_per_winner']:+.3f}, a loser costs {x['loss_per_loser']:.3f}; break-even loss rate {x['breakeven']:.2%}; "
          f"95% upper bound on the true rate {x['upper95']:.2%} -> {'below break-even' if x['proven'] else 'NOT below break-even'}")
    w("\nconcentration by series (top 8 by bets)")
    g = b.groupby("series")
    c = pd.DataFrame({"bets": g.size(), "events": g["event"].nunique(), "sum_ret": g["r"].sum(), "mean_ret": g["r"].mean(),
                      "losing": g["r"].apply(lambda x: int((x < 0).sum()))}).sort_values("bets", ascending=False)
    total = b["r"].sum()
    c["share_of_profit"] = c["sum_ret"] / total if total else np.nan
    w(c.head(8).to_string(float_format=lambda x: f"{x:+.3f}"))
    w(f"  {len(c)} series; the largest has {c['bets'].iloc[0] / len(b):.0%} of the bets")
    q = b["day_contracts"].quantile([0.1, 0.25, 0.5, 0.75]).round(0).tolist()
    dq = b["dvol7"].quantile([0.1, 0.25, 0.5, 0.75]).round(0).tolist()
    w(f"\ncapacity: contracts traded on the entry day, 10/25/50/75th percentile: {q}; "
      f"dollars traded in the 7 days before: {dq}; entry days with under 100 contracts: {(b['day_contracts'] < 100).mean():.0%}")
    h = b["hold"]
    w(f"holding time: median {h.median():.1f} days, mean {h.mean():.1f}; return per year of capital at work "
      f"(sum of returns / sum of holding years): {b['r'].sum() / (h.sum() / 365.25):+.1%}")
    w("\naccount replay (event cap 3%, at most 50% at work), in sample | out of sample")
    for stake in (0.005, 0.01, 0.02):
        a, o = portfolio.run(p, [(mask, side, entry)], stake_frac=stake)
        w(f"  stake {stake:.1%}: " + " | ".join(
            f"{x.bets:4d} bets, {x.total:+.1%} over {x.years:.1f} y ({x.cagr:+.1%}/y), worst drawdown {x.max_dd:.1%}, "
            f"at work {x.exposure:.0%}" for x in (a, o)))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", required=True)
    ap.add_argument("--side", required=True, choices=["yes", "no"])
    ap.add_argument("--entry", required=True, choices=["tk", "mk"])
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
    f = Features(p)
    family, mask = find_rule(f, titles_for(df, args.db), args.rule, args.side, args.entry)
    print(f"\n[{family}] {args.rule} | buy {args.side.upper()} | {'taker' if args.entry == 'tk' else 'resting order'}")
    pd.set_option("display.width", 200)
    print(report(bets_frame(p, mask, args.side, args.entry), p, mask, args.side, args.entry))
    return 0


if __name__ == "__main__":
    sys.exit(main())
