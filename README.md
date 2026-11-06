# quant-starter

Phase 1 groundwork for a ranked, long-only, daily-rebalanced stock strategy.

The pipeline:

```
data.py  ->  features.py  ->  ranking.py  ->  portfolio.py  ->  broker.py
(bars)       (signals)        (scores)        (target weights)   (orders)
```

Your portfolio rules are implemented in `src/portfolio.py`:

- rank the universe by model score each rebalance
- **enter** names in the top-N; **exit** fully when a name drops out of the top-N
- for held names: **add** if its weight is below target (it rallied → target grows),
  **trim** if above target, within a `min_trade_pct` band to avoid churn
- position size = inverse-volatility weighted, capped at `max_weight`

`ranking.py` ships a **momentum baseline** (no ML) and an optional **LightGBM
cross-sectional ranker** that predicts forward excess return. Beat the baseline
after costs before trusting the model.

### Stage B: the model decides count and size (`sizing: "optimizer"`, default)

With `sizing: "optimizer"` the `top_n` / add / trim rules above are bypassed
and `src/optimizer.py` decides everything from the model's output:

1. **Expected return** per stock: `IC × z(score) × stock volatility`, where IC
   is the model's own trailing realised rank correlation. A model that stops
   working automatically shrinks its bets toward cash.
2. **Risk**: a shrunk covariance of recent returns, so correlated names don't
   stack risk.
3. **Cost per stock** (`src/costs.py`): spread + square-root market impact,
   from each stock's daily dollar volume, its volatility and **your account
   size** (`costs.capital`). A thin name is cheap to trade with $50k and
   expensive with $5M, and the optimizer sees that.
4. **Optimizer**: maximise expected return − risk penalty − Σ(per-stock cost
   × trade size), with each name ≤ `max_weight`, total ≤ `1 − cash_buffer`,
   and no single day's trade above `max_participation` of a stock's volume.

Position count, sizes, cash level, turnover, and which liquidity tier the
portfolio reaches into all fall out of that one problem. `min_price` and
`liquidity_top_k` are safety rails, not the decision.

**Appetite is learned too** (`auto_tune`, on by default): at each quarterly
retrain, the last year of allocation is replayed for every combination of
`risk_aversion` × `tc_multiplier` in a small grid, and the best after-cost
Sharpe is adopted going forward. Walk-forward only — nothing from the future
leaks in. The live job reads the latest choice from `data/tune_log.csv`.
Disable with `--no-tune` to see the fixed-setting result side by side.

What you still set: `max_weight` and `cash_buffer` (risk limits — a model
should never raise its own), `costs.capital` (a fact), and the tuning grid
itself. `max_positions` is an optional hard cap, off by default.

Compare against the hand rules any time:
`python scripts/run_backtest.py --sizing rank --top-n 20`, and against
optimistic costs with `--flat-costs`.

## Data: Norgate (Windows)

The project is designed around **Norgate Data, US Stocks Platinum** — delisted
securities and historical index membership, which make backtests
survivorship-bias free. It needs the Norgate Data Updater (NDU) app running on
Windows. `config.yaml` defaults to `provider: norgate`, `universe: liquidity` (top 1,000
by dollar volume, common stock on major exchanges, incl. delisted — not bound
to any index; `universe: norgate` pins to an index instead). Free yfinance remains available for a smoke
test (`--provider yfinance --universe static`). Details and the cleaning plan
are in `DATA_PLAN.md`.

## First session on Windows (~1.5 hours, most of it unattended)

Run these in PowerShell from the project folder.

| Step | Command | Time |
|---|---|---|
| 1. Install | `py -3.12 -m venv .venv; .venv\Scripts\activate; pip install -r requirements.txt` (or just `.\setup.ps1`; bare `python` on this PC is 3.7, too old) | 3–5 min |
| 2. Sanity check | `pytest` — 39 tests should pass | ~1 min |
| 3. Free smoke test | `python scripts/fetch_data.py --provider yfinance --universe static` then `python scripts/run_backtest.py --provider yfinance --universe static` — proves the pipeline on your machine | 10 min |
| 4. Norgate | Sign up (free trial or Platinum), install NDU, let it finish its first download, then `python scripts/norgate_smoke.py` — tells you what your subscription unlocks | 20–40 min, mostly NDU downloading |
| 5. Real data | `python scripts/fetch_data.py` — all US common stock incl. delisted since 2010, liquidity-ranked daily | 20–40 min (several thousand symbols; NDU is local) |
| 6. Baseline | `python scripts/run_backtest.py` — momentum, optimizer sizing, auto-tune on | 5–15 min |
| 7. **First ML run** | `python scripts/run_backtest.py --model lgbm` — walk-forward LightGBM, retrains ~60× | 20–40 min on ~1,000 names |
| 8. Dry-run live job | `python scripts/run_daily.py --dry-run` — scores, optimizes, logs to a local paper account | 2 min |
| 9. Dashboard | `streamlit run dashboard/app.py` | instant |

After step 7 compare `strategy_sharpe` and `mean_ic` between the baseline and
`--model lgbm`, and against `--sizing rank --top-n 20`. If the model doesn't
win after costs, the model is the problem, not the plumbing — that's where
the months go.

## Broker

**Start on Alpaca, plan to graduate to Interactive Brokers.** Alpaca:
commission-free US stocks, free paper trading, fractional shares, a cloud API
with nothing to keep running — the right fit for a daily strategy in liquid
names. IBKR: better routing and execution, which matters once the account is
large enough (roughly six figures and up) that slippage outweighs everything
else; the cost is an API that runs through a gateway app and needs reconnect
logic. Webull's official OpenAPI exists but requires application approval,
charges separately for market data, and the popular Python library for it is
unofficial — not a foundation to build on. The broker layer is one file with
three functions (`src/broker.py`), so switching later is plumbing.

## Running it: nothing stays on

The daily job runs once, a few minutes after the close, and exits — the PC
only needs to be awake for ~10 minutes with NDU open. Set it up in Windows
Task Scheduler: weekdays at `live.schedule_local_time` (16:30 Central),
action `.venv\Scripts\python.exe scripts\run_daily.py`, start in the project
folder, tick "wake the computer to run this task". Have NDU start with
Windows. A missed day is harmless: you keep yesterday's positions. For fully
hands-off, a small Windows VPS can run NDU and the job 24/7.

**Paper trading:** put Alpaca *paper* keys in `.env` (copy from
`.env.example`), run `python scripts/run_daily.py` once by hand to watch it
place orders, then schedule it. The paper account is pre-funded with virtual
cash; its balance can be reset in Alpaca's paper dashboard.

**Going live — checklist:**
1. Paper traded for 2–3 months and the dashboard's realised equity roughly
   tracks the backtest's expectations (IC still positive, costs in line).
2. Open and fund a live Alpaca account (ACH/wire in their dashboard; the bot
   never moves money in or out).
3. In `.env`: live keys, `ALPACA_PAPER=false`. In `config.yaml`: set
   `costs.capital` to the real balance so trade sizes and the cost model match.
4. Start smaller than your final size. The job reads account equity every
   run, so later deposits are deployed automatically.
5. Keep running the dashboard; `health_checks` flags a stale run or a
   drawdown beyond 10%.

## Dashboard

`streamlit run dashboard/app.py` shows: health warnings (stale run, drawdown,
data gaps), live equity and drawdown, current positions with ENTER/ADD/TRIM/
EXIT/HOLD actions from the last run, today's full ranking, recent orders, and
the latest backtest (strategy vs equal-weight, rolling IC, turnover). It
refreshes every 60 s and reads the Alpaca account directly if keys are set.

## Project layout

```
config.yaml           universe, rebalance rules, cost assumptions
src/data.py           fetch + cache daily bars (norgate / tiingo / yfinance)
src/providers_norgate.py  Norgate adapter: bars, security master, index membership
src/dataset.py        config → (close, volume, raw_close, membership)
src/universe.py       static / norgate point-in-time / liquidity universes
src/features.py       momentum, volatility, volume, cross-sectional ranks
src/ranking.py        MomentumRanker, LGBMRanker (walk-forward safe)
src/portfolio.py      your enter / add / trim / exit rules → target weights
src/backtest.py       daily simulation with slippage + commission
src/broker.py         Alpaca paper adapter (+ PaperBroker for dry runs)
scripts/              CLI entry points (incl. norgate_smoke.py)
tests/                unit tests on portfolio logic + backtest sanity
```

## Known gaps (Phase 2 work)

- **Survivorship bias**: solved with Norgate (`universe: norgate` or
  `liquidity`, delisted names included). yfinance runs remain optimistic.
- **Delisting returns**: positions in a name that delists are currently
  closed at its last price; DATA_PLAN.md step 5 adds a proper delisting return.
- **Fills**: the backtest trades at the close with a modelled impact cost; calibrate
  `impact_coef` against real fills once paper trading. A `fills.csv` reconciler is TODO.
- **Calendar alignment / imputed-bar flags**: not yet (DATA_PLAN.md step 2).
- **No fundamentals** yet. Features are price/volume only.
- **Regime awareness**: none. Consider a market-level risk-off switch.

## Rules of the road

1. Paper trade for months before real money.
2. If the model doesn't beat the momentum baseline *after costs*, it isn't adding anything.
3. A sustained daily rank IC of 0.03–0.05 is good. Don't expect more.
4. Nothing here is financial advice.

## Sources for the broker and data choices

- [Norgate Data — Stock Market Packages](https://norgatedata.com/stockmarketpackages.php)
- [norgatedata on PyPI (API and Windows requirement)](https://pypi.org/project/norgatedata/)
- [Sharadar — Subscribe (alternative, Linux-friendly)](https://sharadar.com/subscribe)
- [Webull OpenAPI guide (dev.to, 2025)](https://dev.to/zuplo/webull-api-guide-endpoints-authentication-python-sdks-3a82)
- [IBKR vs Alpaca for automated retail trading (dev.to, 2026)](https://dev.to/pickuma/ibkr-vs-alpaca-for-automated-retail-trading-in-2026-3op4)
