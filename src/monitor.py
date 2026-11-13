"""Read-side helpers for the dashboard. Pure functions over the files the
daily job and backtest write, so they can be unit-tested without Streamlit.

Files (all under data/):
  equity.csv          date, equity, cash, n_positions      (run_daily appends)
  latest_ranking.csv  ticker, score, rank, weight, target  (run_daily overwrites)
  live_state.json     weights + last_exit                  (run_daily)
  orders.log          one JSON line per run                (run_daily)
  backtest_daily.csv  ret, bench_ret, turnover, cost, ic   (run_backtest)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("data")


def _p(name: str, data_dir: Path | str = DATA) -> Path:
    return Path(data_dir) / name


# ------------------------------------------------------------------ writers
def append_equity(date, equity: float, cash: float, n_positions: int, data_dir=DATA) -> None:
    p = _p("equity.csv", data_dir)
    row = pd.DataFrame([{"date": pd.Timestamp(date).date().isoformat(), "equity": equity, "cash": cash, "n_positions": n_positions}])
    if p.exists():
        old = pd.read_csv(p)
        old = old[old["date"] != row["date"].iloc[0]]  # idempotent per day
        row = pd.concat([old, row], ignore_index=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")            # temp file + rename: a crash never truncates the equity log
    row.to_csv(tmp, index=False)
    os.replace(tmp, p)


def write_ranking(scores: pd.Series, weights: pd.Series, prev_weights: pd.Series, top_n: int, data_dir=DATA) -> None:
    df = pd.DataFrame({"score": scores}).sort_values("score", ascending=False)
    df["rank"] = np.arange(1, len(df) + 1)
    df["in_ranking"] = df["rank"] <= top_n
    df["weight"] = weights.reindex(df.index).fillna(0.0)
    df["prev_weight"] = prev_weights.reindex(df.index).fillna(0.0)
    df["action"] = np.select(
        [(df.prev_weight == 0) & (df.weight > 0), (df.prev_weight > 0) & (df.weight == 0), df.weight > df.prev_weight + 1e-9, df.weight < df.prev_weight - 1e-9, df.weight > 0],
        ["ENTER", "EXIT", "ADD", "TRIM", "HOLD"], default="",
    )
    df.index.name = "ticker"
    df.reset_index().to_csv(_p("latest_ranking.csv", data_dir), index=False)


# ------------------------------------------------------------------ readers
def load_equity(data_dir=DATA) -> pd.DataFrame:
    p = _p("equity.csv", data_dir)
    if not p.exists():
        return pd.DataFrame(columns=["equity", "cash", "n_positions"])
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    df["ret"] = df["equity"].pct_change()
    df["drawdown"] = df["equity"] / df["equity"].cummax() - 1
    return df


def load_ranking(data_dir=DATA) -> pd.DataFrame:
    p = _p("latest_ranking.csv", data_dir)
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def load_state(data_dir=DATA) -> dict:
    p = _p("live_state.json", data_dir)
    return json.loads(p.read_text()) if p.exists() else {"weights": {}, "last_exit": {}}


def load_orders(data_dir=DATA, last_n_runs: int = 10) -> pd.DataFrame:
    p = _p("orders.log", data_dir)
    if not p.exists():
        return pd.DataFrame()
    rows = []
    for line in p.read_text().splitlines()[-last_n_runs:]:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        for o in rec.get("orders", []):
            rows.append({"date": rec["date"], **o})
    return pd.DataFrame(rows)


def load_backtest(data_dir=DATA) -> pd.DataFrame:
    p = _p("backtest_daily.csv", data_dir)
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date")
    df["equity"] = (1 + df["ret"]).cumprod()
    df["bench_equity"] = (1 + df["bench_ret"]).cumprod()
    df["drawdown"] = df["equity"] / df["equity"].cummax() - 1
    df["ic_roll"] = df["ic"].rolling(63, min_periods=20).mean()
    return df


# ------------------------------------------------------------------ metrics
def equity_stats(eq: pd.Series) -> dict:
    eq = eq.dropna()
    if len(eq) < 2:
        return {}
    r = eq.pct_change().dropna()
    yrs = max(len(r) / 252, 1e-9)
    return {
        "total_return": float(eq.iloc[-1] / eq.iloc[0] - 1),
        "cagr": float((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1),
        "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else float("nan"),
        "max_dd": float((eq / eq.cummax() - 1).min()),
        "days": int(len(eq)),
    }


def health_checks(equity: pd.DataFrame, ranking: pd.DataFrame, today=None) -> list[tuple[str, str]]:
    """Return (level, message) warnings for the dashboard header."""
    today = pd.Timestamp(today or pd.Timestamp.today().normalize())
    out = []
    if equity.empty:
        out.append(("warn", "No live equity history yet — run scripts/run_daily.py"))
    else:
        age = (today - equity.index[-1]).days
        if age > 3:
            out.append(("error", f"Last run was {age} days ago — is the scheduler alive?"))
        dd = float(equity["drawdown"].iloc[-1])
        if dd < -0.10:
            out.append(("error", f"Drawdown {dd:.1%} from peak"))
        elif dd < -0.05:
            out.append(("warn", f"Drawdown {dd:.1%} from peak"))
    if not ranking.empty and "score" in ranking and ranking["score"].isna().mean() > 0.2:
        out.append(("warn", f"{ranking['score'].isna().mean():.0%} of universe has no score — data gaps?"))
    return out
