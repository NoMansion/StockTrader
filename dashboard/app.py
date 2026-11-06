"""Live dashboard. Run from the project root:

    streamlit run dashboard/app.py

Reads the files the daily job and backtest write (see src/monitor.py) and,
if Alpaca keys are in .env, the live account. Auto-refreshes every 60s.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from src.monitor import (  # noqa: E402
    equity_stats, health_checks, load_backtest, load_equity, load_orders, load_ranking, load_state,
)

st.set_page_config(page_title="quant-starter", layout="wide")
st.markdown("<meta http-equiv='refresh' content='60'>", unsafe_allow_html=True)

st.title("quant-starter — live")

equity = load_equity()
ranking = load_ranking()
state = load_state()
orders = load_orders()
bt = load_backtest()

# ---------------------------------------------------------------- health
for level, msg in health_checks(equity, ranking):
    (st.error if level == "error" else st.warning)(msg)

# ---------------------------------------------------------------- account
acct_col, pos_col, dd_col, n_col = st.columns(4)
live_equity = None
try:
    if os.environ.get("ALPACA_API_KEY"):
        from src.broker import AlpacaBroker
        b = AlpacaBroker()
        live_equity = b.equity()
        live_positions = b.positions()
except Exception as e:  # keys missing, network, etc.
    st.caption(f"Alpaca not reachable: {e}")

if live_equity is not None:
    acct_col.metric("Equity (Alpaca)", f"${live_equity:,.0f}")
elif not equity.empty:
    acct_col.metric("Equity (last run)", f"${equity['equity'].iloc[-1]:,.0f}")
else:
    acct_col.metric("Equity", "—")

stats = equity_stats(equity["equity"]) if not equity.empty else {}
pos_col.metric("Total return", f"{stats.get('total_return', 0):+.1%}" if stats else "—")
dd_col.metric("Drawdown", f"{equity['drawdown'].iloc[-1]:.1%}" if not equity.empty else "—")
n_col.metric("Positions", int(equity["n_positions"].iloc[-1]) if not equity.empty else len(state["weights"]))

# ---------------------------------------------------------------- equity curve
st.subheader("Equity")
if equity.empty:
    st.info("No live history yet. Run `python scripts/run_daily.py --dry-run` once to populate.")
else:
    st.line_chart(equity[["equity"]])
    st.area_chart(equity[["drawdown"]])

# ---------------------------------------------------------------- positions & ranking
left, right = st.columns([1, 1])
with left:
    st.subheader("Positions")
    if ranking.empty:
        w = pd.Series(state["weights"], dtype=float)
        st.dataframe(w.rename("weight").to_frame() if not w.empty else pd.DataFrame())
    else:
        held = ranking[ranking["weight"] > 0].sort_values("weight", ascending=False)
        st.dataframe(
            held[["ticker", "rank", "score", "prev_weight", "weight", "action"]].style.format(
                {"score": "{:.3f}", "prev_weight": "{:.1%}", "weight": "{:.1%}"}
            ),
            hide_index=True, width="stretch",
        )
        st.bar_chart(held.set_index("ticker")["weight"])

with right:
    st.subheader("Today's ranking")
    if ranking.empty:
        st.info("Run the daily job to produce a ranking.")
    else:
        top = ranking.sort_values("rank").head(40)
        st.dataframe(
            top[["rank", "ticker", "score", "in_ranking", "action"]].style.format({"score": "{:.3f}"}),
            hide_index=True, width="stretch", height=600,
        )

# ---------------------------------------------------------------- orders
st.subheader("Recent orders")
if orders.empty:
    st.caption("No orders logged yet.")
else:
    st.dataframe(orders.sort_values("date", ascending=False), hide_index=True, width="stretch")

# ---------------------------------------------------------------- backtest
st.subheader("Latest backtest")
if bt.empty:
    st.caption("Run `python scripts/run_backtest.py` to populate.")
else:
    s = equity_stats(bt["equity"])
    b = equity_stats(bt["bench_equity"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Strategy CAGR", f"{s['cagr']:.1%}", delta=f"{s['cagr'] - b['cagr']:+.1%} vs EW")
    c2.metric("Sharpe", f"{s['sharpe']:.2f}", delta=f"{s['sharpe'] - b['sharpe']:+.2f}")
    c3.metric("Max drawdown", f"{s['max_dd']:.1%}")
    c4.metric("Mean IC", f"{bt['ic'].mean():.3f}")
    st.line_chart(bt[["equity", "bench_equity"]].rename(columns={"equity": "strategy", "bench_equity": "equal-weight"}))
    cc1, cc2 = st.columns(2)
    cc1.caption("Rolling 63-day IC (model health — should stay > 0)")
    cc1.line_chart(bt[["ic_roll"]])
    cc2.caption("Daily turnover")
    cc2.line_chart(bt[["turnover"]])
