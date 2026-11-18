# PolymarketTrader

An experiment: Claude forecasts prediction-market questions, and plain code decides whether a forecast is worth a
small bet. It runs on **paper only** for now, against live prices from Polymarket US (the CFTC-regulated venue open
to US residents). No keys, no wallet and no money are involved until the paper record passes the gates in
`docs/GO_LIVE.md`.

Status, 2026-11-18: built and unit-tested (128 tests) in a cloud session that could not reach the exchange. **It
has not yet run against real market data.** The first run on the PC is the first real test; see "Not yet verified".

## What the research says (and how the design follows)

The full report is `reports/Claude Polymarket trading strategies.md`. Five findings shaped everything here:

| Finding | What the bot does about it |
|---|---|
| The viral "Claude bot made $X" stories are Claude writing code for speed or arbitrage bots; none is a verified case of Claude forecasting profitably, and Polymarket closed those speed edges with fees in 2026. | No latency, arbitrage, copy-trading or short-dated crypto strategy. |
| Where a language model made the trading decisions with real money, it lost (six models, average −22.6% on Kalshi; Claude Opus 4.5 −25.9% over 886 trades). Models are close to the market on accuracy, not ahead of it. | Trade rarely. Most cycles end with no order. |
| The one positive result: a model forecast **blended with the market price** beats the price alone, by a little. | The market price is the starting point; Claude moves it 30% of the way. Claude is not shown the price. |
| Accounts that rest limit orders make money; accounts that take prices lose it, worst of all on longshots. Takers pay a fee (about 2.4 cents a share at 50 cents on Polymarket US); makers pay none. | Entries are resting limit orders below the ask. No contract under 12 cents. Hold to settlement. |
| The losses that wipe accounts are disputed resolutions, insider-heavy markets and stolen keys, not ordinary bad forecasts. | Claude must restate the rules and say if they are unclear; announcement, military, award and "mention" markets are excluded; no third-party bot code; no key on the machine during paper trading. |

The honest expectation from that evidence is a result near zero. The experiment's real product is the forecast
log: whether Claude's numbers beat the market's own prices can be measured long before profit can.

## How a cycle works

```
venue.py      universe.py       forecast.py           sizing.py            safety.py        broker.py
(markets,  -> (rule filters) -> (Claude: probability -> (blend with price, -> (limits, kill  -> (paper orders)
 books)                          + reasons, 3 runs)     fractional Kelly)     switch)
                                        every forecast, decision, fill and price: ledger.py (data/pmt.db)
```

1. **Mark.** Refresh prices for everything held or recently forecast. Settle resolved markets. Fill or expire
   resting paper orders.
2. **Safety.** Kill switch, drawdown, total loss, daily budget.
3. **Forecast.** Filter the exchange's open markets by rule. For the few that pass (4 per cycle by default), ask
   Claude. Each market gets 3 independent runs with web search; the median is used. Runs that disagree by more
   than 15 points, low confidence, unclear rules or any raised flag mean no trade.
4. **Exits.** Sell a held position only if a fresh forecast has reversed the edge. No price stop-losses.
5. **Entries.** Blended probability = market + 0.3 × (Claude − market). Trade only if that beats the price paid by
   3 points or more. Stake = a quarter of the Kelly fraction, capped at 2% of the account per market.
6. **Record.** Every decision is logged with its reason, including every trade not taken.

Claude's part ends at step 3. It returns a number and its reasoning in a fixed format, with only web search
available to it: no shell, no files, no order code. Whatever a web page says to it, it has nothing to act with.

## The limits

| Rule | Setting | Where |
|---|---|---|
| Markets considered | 3 to 45 days from resolution, priced 15 to 85 cents, spread 4 cents or less, sports / crypto / weather / mentions / culture excluded | `universe` in `config.yaml` |
| Model weight | 0.3 toward Claude, 0.7 on the market price | `sizing.shrink_weight` |
| Minimum edge | 3 points after blending (about 10 points of raw disagreement) | `sizing.min_edge` |
| Disagreement ceiling | above 25 points, assume we are wrong: no trade | `sizing.max_disagreement` |
| Stake | quarter Kelly, at most 2% of equity per market, 4% per event, 20% per category, $50 per order | `sizing` |
| Cash | at least 60% of the account stays uninvested | `sizing.max_total_exposure_pct` |
| Daily budget | 6 orders and 10% of equity per 24 hours | `safety` |
| Drawdown | 15% from the peak: no new positions until reviewed | `safety.max_drawdown` |
| Total loss | 25% of the money deposited: the experiment stops | `safety.max_total_loss` |
| Kill switch | create the file `data/STOP` (`STOP.txt` also counts); checked at the start of a cycle and again before every order; cancels resting orders; delete it to resume | `safety.kill_switch` |
| Real money | not implemented; `account.mode: live` refuses to start | `src/broker.py` |

A model should never be able to raise its own limits. These live in `config.yaml` and `src/safety.py`, are checked
after the forecast, and the forecaster is never told what they are.

## First session on Windows (about 15 minutes)

Run in PowerShell from the project folder.

| Step | Command | What it shows |
|---|---|---|
| 1. Install, test, demo | `Set-ExecutionPolicy -Scope Process Bypass; .\setup.ps1` | 128 tests pass; a made-up month of trading prints a status report |
| 2. Look at the real market list | `.venv\Scripts\python scripts\run_cycle.py --scan` | How many live markets pass the filters, and why the rest are dropped. Changes nothing, calls Claude zero times. **This is the first contact with the real exchange: expect surprises here.** |
| 3. One real paper cycle | `.venv\Scripts\python scripts\run_cycle.py` | Up to 4 markets forecast by Claude (several minutes), any paper orders placed |
| 4. Status | `.venv\Scripts\python scripts\status.py` | Account, positions, forecast scoring, go-live gates |

The forecaster needs the Claude Code command (`claude`) installed and signed in for the Windows user that runs
the job. Check with `claude -p "say ok"`.

## Running it unattended

One cycle every 8 hours is plenty: these markets resolve over days and weeks, and forecasts are refreshed every
48 hours. Schedule it away from the stock trader's evening job (the bot also refuses to run between 17:15 and
18:20 local time, `runtime.quiet_windows`):

```
schtasks /create /tn "PolymarketTrader Cycle" /sc hourly /mo 8 /st 07:40 /f /tr "wscript.exe //B \"E:\Coding\PolymarketTrader\scripts\run_cycle_hidden.vbs\""
```

That runs at 07:40, 15:40 and 23:40, hidden, logging to `data\run_cycle.log` and refreshing `data\status.md`.
Like the stock trader's task, it runs only while the user is logged in. A missed cycle is harmless.

**What it costs the PC.** One Python process using a few megabytes, a few dozen small web requests half a second
apart, and one Claude process at a time. It runs at below-normal priority, will not start with under 1.5 GB of
memory free, and a lock file stops two cycles overlapping. It holds no data in memory between cycles.

**What it costs in Claude usage.** With the defaults, at most 4 markets × 3 runs × 3 cycles = 36 research runs a
day against the Claude subscription, about a minute each. Lower `forecaster.runs` or
`universe.max_candidates_per_cycle` if that crowds out other work. The `api` backend does the same on a paid API
key at roughly $0.30 to $0.60 a forecast, which is more than a $20 bet with a 4-point edge is expected to earn:
use it only with a reason.

## Reading the results

`scripts/status.py` answers three questions, in the order they become answerable:

1. **Does the market move toward Claude's number after a forecast?** Available within days. No resolutions needed.
2. **Is Claude's Brier score better than the market's on the same questions?** Needs 30 resolved markets for a
   first look and 100 or more to conclude. If Claude is measurably *worse*, stop.
3. **Did the paper account make money?** The noisiest measure: a 5-point edge needs about 400 independent bets to
   show up in the win rate. A good or bad month means little.

Paper results will flatter reality. The simulator is deliberately pessimistic (resting orders fill only when the
price moves against them, and an order left resting in a market that closes against it is counted as filled;
positions are valued at the bid), but one published comparison of the same strategy on
the same venue showed +49.8% on paper and +5.9% for real.

## Not yet verified

Everything about the exchange was read from the official `polymarket-us` 2.4.1 SDK source, not observed on the
wire. The first `--scan` on the PC will show which of these need a fix:

- **Field names** for a market's end date, rules text and category beyond the ones the SDK declares
  (`src/venue.py` tries several spellings and treats a missing end date or rules text as "do not trade").
- **Category labels** the exchange actually uses, which the deny list in `config.yaml` must match. A market with
  no category or tags at all is not traded, so if the scan drops everything for "no category or tags", the field
  mapping in `src/venue.py` is the thing to fix.
- **Settlement**: what the settlement endpoint returns before a market has settled. The bot only settles a market
  the exchange reports as closed, and only at a payout of exactly 0, 0.5 or 1.
- **Fees, tick size, minimum order size**: `fees.taker_rate` (0.095) and `execution.tick` (0.01) come from
  secondary sources dated November 2026 and the fee schedule was changing that month.
- **State eligibility**: sources conflict on which states Polymarket US accepts (Illinois is one of the disputed
  ones). Only the app's own sign-up check settles it. Kalshi is the fallback venue; an adapter for it is not written.
- Most figures in the research report came from search summaries, because the research session could not open
  the primary pages. The report's last table lists what to re-check before real money.

Differences from the report's recommended design, on purpose or not yet done: 3 forecast runs instead of 5 to 10
(usage cost); no allow-list of web sources (the Claude Code web search cannot be restricted that way; the run
spread check, the flags and the caps stand in for it); no recalibration of Claude's probabilities yet (needs 100+
of its own resolved forecasts first); no second paper venue.

## Layout

```
config.yaml           every setting, with the reason for it
src/venue.py          Polymarket US market data (read-only, public endpoints)
src/universe.py       which markets get a forecast
src/forecast.py       Claude as forecaster: prompt, answer format, three backends
src/sizing.py         blend with the market, fractional Kelly, caps
src/safety.py         account and per-order limits, kill switch
src/book.py           order book and pessimistic fill simulation
src/broker.py         paper broker (resting and taker orders); live broker is a stub
src/ledger.py         SQLite record of everything
src/scoring.py        Brier vs market, price movement, P&L, go-live gates
src/trader.py         the cycle
src/runtime.py        lock, quiet hours, priority, memory check
scripts/              run_cycle.py, status.py, demo_offline.py
tests/                128 tests, all offline
reports/              the research report
research_notes/       the six sets of notes behind it
docs/GO_LIVE.md       what has to be true before real money, and how to do it then
```

## Rules of the road

1. Paper trade for at least eight weeks and until the gates in `docs/GO_LIVE.md` pass. Do not move the gates.
2. If Claude's forecasts are not better than the market price, the forecasts are the problem, not the plumbing.
3. Never install someone else's Polymarket bot, skill or connector on this PC. That niche is full of key stealers.
4. Use only a venue that accepts your state. The international polymarket.com site is closed to US residents.
5. Money put in here can be lost in full. Nothing here is financial, legal or tax advice.
