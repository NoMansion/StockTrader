# Quant-starter: model, data sources and next tests
*Status as of Monday 2026-11-09, 9:00 pm CT. Sweep: 807 backtests done, 127 queued. Running on one worker at idle priority while the PC is in use; the 14 remaining useful runs (sleeve + vol-target combinations, Sharadar tilts with the sleeve) finish around 11 pm, the low-value older queue runs into tomorrow.*

## 1. Summary

- **The paper account runs the Sharpe-optimized model** since this morning's open: 55 names, inverse-volatility sizing, equal sector split, 10-day re-entry cooldown, exposure scaled by a 15% vol target, halved when the universe is down over 12 months, halved again while NYSE new lows outnumber new highs. It is currently 33% invested (the breadth gate is on). 26-year stitched record: 7.5% CAGR, Sharpe 0.79, worst drawdown −13%, worst year −8%.
- **The biggest finding since Friday is sizing, not signals.** Inverse-vol sizing lifted the stitched Sharpe from 0.63 to 0.73 on its own; the breadth gate and cooldown took it to 0.79. Every ranking tweak tested was noise by comparison.
- **New leader: momentum tilted 30% toward free-cash-flow yield, 3-day rebalancing, T-bill yield and the IEF/GLD sleeve: stitched Sharpe 1.00, 10.6% CAGR, −18% drawdown, worst year −11% (2022).** The first setup over 1.0. Without the Sharadar tilt the same stack scores 0.97 / 11.0% / −21%, so the tilt buys lower drawdown rather than return; running it live needs `model.fundamentals: sharadar`. Rebalancing every third day instead of daily cut turnover from 7.7% to 5.6% of the book per day and lifted the plain model from 0.79 to 0.84 on its own; the sleeve and cash yield add the rest. Anti-churn bands helped less (0.78–0.84) and a wider exit band did nothing.
- **Idle cash matters as much as the stock picks.** The gated model holds 40–70% cash most of the time. An always-on equal mix of IEF and GLD on that cash scores 0.93 stitched, 10.3% CAGR, −19% drawdown. The long-bond version (TLT) looked better until you check 2022, where it lost 18%. Trend-filtering the sleeve made it worse.
- **Sharadar verdict: the earnings signal is real, and the criterion is met for the pure version.** With Sharadar's 1998+ fundamentals, ranking on earnings surprise alone scored 0.80 on the 2000–2010 decade it had never seen, against 0.72 for momentum, and 0.83 stitched over 26 years against 0.79. With the IEF/GLD sleeve it reaches 0.97, the highest stitched Sharpe of the whole project. But every blend that mixes earnings into the momentum score came out *below* plain momentum on the clean data, and a portfolio-level 50/50 split adds only +0.04 because the two books share the exposure gates and move together. Section 5 has the detail and the keep-or-cancel options.
- **A realistic forward expectation** for the Sharpe line is 8–9% a year including T-bill interest on idle cash, with a drawdown budget around −15%. The growth line (section 3) trades that for 10–12% at −20% to −35%. No setup tested compounds above 12.4% over 26 years without leverage; the "17%" was the 2010–2026 in-sample figure for a model that made 2.7% in the 2000s.

## 2. Where the model stands

Stitched = 2000–2010 run with rules frozen (out-of-sample) joined to the 2010–2026 run. Benchmark is the equal-weight universe: 9.1% CAGR, Sharpe 0.50, −58% drawdown.

| Setup (all k450, 55 names, sector-equal) | CAGR | Sharpe | Max DD | Worst year | Beat bench |
|---|---|---|---|---|---|
| Rank sizing, no exposure control (the "17%" model) | 11.1% | 0.56 | −56% | −44% | 12/26 |
| + vol target 15% + 12m trend gate | 9.9% | 0.62 | −32% | −33% | 13/26 |
| + inverse-vol sizing | 7.7% | 0.73 | −20% | — | 12/26 |
| + breadth gate + 10d cooldown (**paper account**) | 7.5% | 0.79 | −13% | −8% | 12/26 |
| + IEF/GLD sleeve on idle cash | 10.3% | 0.93 | −19% | −12% | 14/26 |
| + 3-day rebalance + T-bill yield + IEF/GLD sleeve | 11.0% | 0.97 | −21% | −13% (2022) | 14/26 |
| same, momentum tilted 30% toward FCF yield (Sharadar) (**new leader**) | 10.6% | **1.00** | −18% | −11% (2022) | 13/26 |
| same, earnings surprise + FCF yield ranker, no momentum | 9.7% | 0.99 | −17% | −8% | 11/26 |
| 3-day rebalance alone (no sleeve) | 8.1% | 0.84 | −14% | −8% | 13/26 |
| + SHY/IEF/GLD sleeve | 9.5% | 0.92 | −16% | −11% | 13/26 |
| + TLT/IEF/GLD sleeve | 10.0% | 0.92 | −24% | −18% (2022) | 13/26 |
| + GLD-only sleeve | 11.3% | 0.83 | −33% | −10% | 14/26 |

Per-year, the paper model's worst years are 2008 (−8%), 2022 (−6%), 2002 (−4%). It made 10% in 2020 and 32% in 2024.

**Walk-forward check.** Re-selecting the best setup every five years on the prior five years' Sharpe, out of 174 stitched setups, the pick landed in the top 6% of the pool in every following block and the re-picked path scored 0.96 Sharpe over 2006–2026. The family choice (inverse-vol + gates + defensive sleeve) is stable. Fine ordering is not: rank correlation of setup Sharpes between consecutive blocks is 0.1–0.2, so differences under about 0.03 are noise. Caveat: the pool was built with full-sample knowledge, so this understates selection bias.

## 3. The risk/return frontier (growth-weighted round)

Queued at your request this morning; the exposure dial loosened while keeping inverse-vol, sector split and cooldown. Results so far (stitched 2001–2026):

| Setup | CAGR | Sharpe | Max DD | Worst year | Calmar |
|---|---|---|---|---|---|
| Paper model (vt15 + gates) | 7.5% | 0.79 | −13% | −8% | 0.58 |
| vt20 + gates | 8.1% | 0.79 | −16% | −10% | 0.51 |
| vt25 + gates | 8.3% | 0.78 | −17% | −11% | 0.49 |
| Gates only, no vol target, inverse-vol | 9.0% | 0.74 | −28% | −14% | 0.32 |
| Gates only, rank sizing | 10.9% | 0.68 | −26% | −14% | 0.41 |
| vt25 + gates, rank sizing | 10.7% | 0.68 | −26% | −11% | 0.42 |
| vt30 + gates | 8.2% | 0.77 | −18% | −11% | 0.47 |
| vt20 + gates, 33 names | 8.5% | 0.77 | −17% | −9% | 0.49 |
| vt20 + softer trend gate (70% not 50%) | 8.4% | 0.80 | −18% | −10% | 0.48 |
| Paper model + T-bill yield on idle cash | 8.1% | 0.85 | −12% | −7% | 0.69 |
| IEF/GLD sleeve on paper model | 10.3% | 0.93 | −19% | −12% | 0.54 |
| vt20 + TLT/IEF/GLD sleeve | 10.2% | 0.90 | −24% | −18% | 0.43 |
| GLD sleeve on paper model | 11.3% | 0.83 | −33% | −10% | 0.35 |

Reading: the exposure dial is nearly exhausted. Raising the vol target from 15% to 30% adds 0.7 points of CAGR; the trend and breadth gates do most of the de-risking and they stay on. Fewer names and a softer trend gate change little. Removing the vol target entirely adds 1.5 points for double the drawdown, and rank sizing adds another 2 points for a similar drawdown. The two changes that raise return without lowering Sharpe are both about the cash: paying T-bill interest on it, and putting it in the IEF/GLD sleeve. The frontier bends around 10–11% CAGR at −19% to −26% drawdown; beyond that, extra return comes at roughly four times the drawdown. Sleeve-on-growth-base combinations are still running.

## 4. Data sources tested

| Source | Cost | Used for | Result | Keep? |
|---|---|---|---|---|
| Norgate prices + membership (NDU) | already paid | universe, momentum, vol, sizing | the base; delisting-aware, point-in-time membership | yes |
| Norgate breadth series (#NYSEHI/LO, #NYSEAD) | included | breadth gates | new-highs-minus-lows 10d gate: +0.03 Sharpe on every base; A/D gate: neutral-to-slightly positive | yes (hl10 live) |
| Norgate macro/credit series (NFCI, CFNAI, claims, credit spreads, curve, PMI, unemployment) | included | regime gates | CFNAI and NFCI pass both halves but add less than hl10; credit, curve, HY, PMI, unemployment, TRIN fail out-of-sample | not live |
| Put/call ratio | included | sentiment gate | passes both halves (0.67), overlaps hl10 | not live |
| VIX level and term structure | included | exposure | worse than realized-vol targeting on every base, especially 2000s | no |
| ETF prices TLT/IEF/GLD/SHY, spliced to bond and commodity indices pre-2002/2004 | included | idle-cash sleeve | IEF+GLD always-on: +0.14 Sharpe, +2.8 pts CAGR; TLT adds 2022 risk; trend/momentum rules on the sleeve hurt | **yes, candidate for live** |
| 13-week T-bill yield (%IRX) | included | cash yield on idle balance | +0.6 to +1.1 pts CAGR, Sharpe roughly unchanged; real money earns this anyway | yes (accounting) |
| SEC EDGAR XBRL fundamentals (free, 2009+) | free | earnings surprise, NI growth, gross profitability, accruals | SUE and NI-growth tilts pass; gross profitability and accruals fail | yes, see §5 |
| SEC Form 4 insider trades (free, 2006+) | free | net buying, cluster buys, net $ | all variants ≤ 0.73 vs 0.72 base; no signal at this horizon | no |
| Dividend yield | included | tilt | neutral | no |
| Sharadar fundamentals (1998+) | $19/mo, bought today | earnings tilt on the 2000s OOS decade; factor zoo | earnings-only passes OOS (+0.08 vs momentum) and stitched (+0.04); blends fail; factor zoo running | see §5 |

**Cost stress.** The sweep's earlier 25k / 1M / 5M capital, 6 bps spread and doubled impact cases all returned identical results because the cost model clips every trade at a 10 bps floor and the top-450 universe never exceeds it. The real sensitivity is to that floor, and it is steep because the paper model turns over 7.7% of the book per day (about 19 times a year, one way):

| Cost per trade (one way) | Cost drag / yr | 26-yr CAGR | 26-yr Sharpe |
|---|---|---|---|
| 10 bps (assumed) | 2.0% | 7.5% | 0.79 |
| 15 bps | 3.0% | 6.4% | 0.69 |
| 20 bps | 4.0% | 5.4% | 0.59 |
| 30 bps | 6.1% | 3.4% | 0.39 |

Each extra 5 bps per trade costs about 1 point of CAGR and 0.1 of Sharpe. On top-450 names with Alpaca's commission-free fills at the open, 10 bps is a fair central estimate, but it has to be verified against live fills (item 12 in section 6). A $1-per-trade commission on a $25k account (a non-Alpaca broker) would be ruinous at this turnover: 13% a year. Cutting turnover is therefore worth as much as a new signal; a round testing 3- and 5-day rebalancing, anti-churn bands and a wider exit band is queued.

## 5. The Sharadar results

You bought the Fundamentals plan at midday and the test ran this afternoon. Setup: full-history quarterly fundamentals (685k as-reported rows, 17k tickers, 12k of them delisted) mapped onto the Norgate universe by ticker and delisting date (3,254 of 3,471 names matched; the rest are mostly bankruptcies and foreign ADRs), built into a point-in-time panel with the same feature definitions as the EDGAR one. Coverage: ~900 universe names in 2000, ~1,700 from 2005.

**Same base, same rankers, three windows** (base = inverse-vol + gates + cooldown, momentum ranker c189_f):

| Ranker | 2000–2010 OOS Sharpe | 2010–2026 Sharpe (holdout 2021+) | Stitched 26-yr Sharpe | 26-yr CAGR |
|---|---|---|---|---|
| Momentum (base) | 0.72 | 0.83 (0.93) | 0.79 | 7.5% |
| **Earnings surprise only** | **0.80** | 0.84 (1.18) | **0.83** | 6.7% |
| Earnings + NI growth | 0.84 | 0.74 (0.85) | 0.78 | 6.5% |
| Momentum + 30% SUE | 0.78 | 0.75 (0.97) | 0.76 | 6.9% |
| Momentum + 50% SUE | 0.79 | 0.76 (0.89) | 0.77 | 6.8% |
| Momentum + NI-growth | 0.72 | 0.79 (1.00) | 0.77 | 7.2% |
| Momentum + decayed SUE | 0.77 | 0.76 (0.96) | 0.76 | 7.0% |
| Momentum + quality (gprof, SUE, accruals) | 0.79 | 0.74 (0.87) | 0.76 | 7.1% |
| Base + IEF/GLD sleeve | — | — | 0.93 | 10.3% |
| **Earnings only + IEF/GLD sleeve** | — | — | **0.97** | 9.6% |

**What this says.**
- The earnings signal is real across all 26 years. Pure earnings surprise beat momentum in the 2000s (+0.08) and matched it in 2010–2026 with a much stronger recent holdout. It turns over less (5.9%/day vs 7.7%) and draws down less.
- Blending it *into* the momentum score does not work. Every blend sits below plain momentum on the stitched record (0.76–0.78 vs 0.79). Averaging two different rankings dilutes both; this held on EDGAR too once the Sharadar panel removed its staleness.
- Combining at the portfolio level (half the book on each ranker) gives 0.83, the same as earnings alone, because the two books share the exposure gates and are 0.90 correlated day to day. With both sleeved, a 30% momentum / 70% earnings split reaches 0.97.
- The price of the Sharpe gain is return: earnings-only compounds 0.8 points a year slower than momentum.
- The free EDGAR panel, checked against Sharadar, was missing quarters for about a fifth of names and a year stale for 2%. It was good enough to find the signal, not good enough to size it.

**Keep or cancel.** The data case for keeping Sharadar depends on one decision: whether earnings surprise goes into the live model. Three options, as data economics only:
1. *Momentum only, cancel Sharadar after the month.* Give up roughly +0.04 Sharpe. Nothing recurring. Simplest live pipeline.
2. *Earnings-only (or 30/70 two-book) with the IEF/GLD sleeve, keep Sharadar Fundamentals at $19/month alongside Norgate.* Highest Sharpe found (0.97), lower CAGR than the momentum-plus-sleeve line (9.6% vs 10.3%). Needs the panel refreshed daily in `run_daily`, about a day's work.
3. *Move everything to Sharadar (Fundamentals + Prices, $28/month) and drop Norgate.* Possible but one to two days to rebuild the data layer and re-validate, and the breadth series would have to be computed from prices. Only worth it if Norgate's cost is the deciding factor.

I am not a licensed advisor; this is a statement about what the data supports, not about what to do with your money.

**Factor zoo on 26 years (round 22, Sharadar point-in-time data, same inverse-vol + gates base).** Standalone rankers, stitched Sharpe / CAGR: earnings surprise + FCF yield 0.86 / 7.0%, ROE 0.84 / 6.5%, FCF yield 0.83 / 7.1%, earnings surprise 0.83 / 6.7%, buybacks 0.82 / 6.5%, five-factor quality 0.80 / 6.3%, earnings yield 0.79 / 6.7%, low asset growth 0.76, sales growth 0.57. Every fundamental ranker beats momentum (0.79) on Sharpe and loses to it on return, with turnover of 4–6% a day against 7.7%. Tilting momentum toward a fundamental factor is mostly neutral or worse (0.73–0.77) with one exception, the 30% FCF-yield tilt at 0.84 / 7.3% / −12%, which is what the new leader builds on. Mixed into the sleeve stack the same ordering holds: FCF-tilt 1.00, surprise + FCF 0.99, surprise alone 0.97, FCF alone 0.95, ROE 0.95.

**Weights and vol targeting (round 23).** A grid of eight momentum/consistency weightings on the full stack scored 0.72–0.80 against 0.79 for the current weights, and re-picking the weights every five years from the prior block gives a walk-forward path of 0.77 Sharpe and 7.5% CAGR, the same as the fixed weights. The Sharpe is not coming from the weights, so there is little parameter luck in them. Targeting the strategy's own realized vol (12%, 15%, 20%, and a 60-day window) instead of the universe index scored 0.74–0.78: a dead end.

## 6. Options for continued tests

Already queued (will run through this evening, ~2–3 hours each block on six workers):

1. **Growth frontier, pass 2** — IEF/GLD sleeve on each growth base (vt20, vt25, gates-only, rank-sized); 33-name books; vt30.
2. **Sleeve sizing** — IEF/GLD at 50% and 75% of idle cash, with and without T-bill yield; GLD-only at half size; SHY/IEF/GLD with yield.
3. **Earnings blends on the growth bases** — 30%/50% SUE and NI-growth on vt20 and on rank-sized gates-only; SUE-only and NI-growth with the sleeve.
4. **Post-earnings drift timing** — SUE counted only while under 63 days old, and SUE decayed with a two-month half-life, alone and at 30–50% blend weight.
5. **Cost stress that binds** — floors of 15, 20, 30 bps; $1/trade commission at $25k.
6. **Turnover reduction** — 3- and 5-day rebalancing, anti-churn bands of 30% and 50% of target, a 2× exit band, and the combined candidate (3-day rebalance + T-bill yield + IEF/GLD sleeve). Each 5 bps saved per trade is worth a point of CAGR.
7. **Sharadar factor zoo on 26 years** — free-cash-flow yield, earnings yield, sales growth, asset growth (negative), buybacks, ROE, a five-factor quality composite, and tilts of each into momentum. The first time any of these can be tested on the 2000s with point-in-time data.
8. **Older queue** — 21 auto-combination variants, 14 sector-momentum/residual/seasonality ideas, 15 Friday-rule variants, 48 exposure-dial refinements on the old rank base (lowest value; last in line).

Items 9–14, queued or built this afternoon at your request:

9. **Walk-forward with re-fitted weights** — done. The eight-weighting grid scored 0.72–0.80 stitched; re-picking the weights every five years gives a 0.77 path, equal to the fixed weights. Parameter luck in the weights is small (section 5).
10. **Sleeve, cash yield and Sharadar fundamentals are now first-class in src** (not sweep-only code any more). Config: `portfolio.sleeve`, `portfolio.cash_yield`, `model.fundamentals: sharadar`. The daily script adds the ETF targets to the order list and loads the fundamentals from the Sharadar API with a local cache. All off by default; the paper account is unchanged until you say so.
11. **Opening-auction orders** — `live.order_type: opg` sends whole-share market-on-open orders (the fill the backtest assumes), with the sub-share remainder as a small notional order. Default stays `market`.
12. **Vol target from the strategy's own realized vol** — done, dead end: 0.74–0.78 against 0.79 for the universe-index target.
13. **Live-vs-backtest reconciliation** — `scripts/reconcile_fills.py` pulls the fills behind the ids in orders.log and compares them with the Norgate open and prior close in basis points. First look at today's 55 fills: all filled between 9:30:00 and 9:35:43; Norgate publishes today's bars this evening, so the first slippage numbers come tomorrow.
14. **Two-book live structure** — `portfolio.books` runs several rankers with their own capital share, top-N and state file, and adds their targets (the backtest runner combines them the same way). The momentum + earnings split from section 5 can be run live once you want it.

Still open: the last 14 runs of the sleeve rounds (vol target 20–25% and the rank-sized base with the sleeve; Sharadar tilts with the sleeve), and reading the first week of fill reconciliation before changing the cost floor.

Not worth it at this account size, with the reason:

- **Intraday data or VWAP execution** — at $25k–$100k the fills are a rounding error on top-450 names.
- **Options overlays** — premium and spreads exceed the drawdown they would save at this size.
- **Alternative data vendors (web traffic, credit card, satellite)** — thousands per month; no path to paying for itself under ~$1M.
- **Shorting** — margin cost and borrow fees against a signal whose long side carries the edge.
- **More ranking-formula variants** — 100+ tested; nothing beat the consistency blend by more than noise. Sizing and exposure are where the gains were.

## 7. Operational notes

- Paper account: 55 positions, $32.9k invested, 0 open orders, equity $100,274 at 9 pm.
- **The first automatic 16:30 run was killed.** Task Scheduler ran it, but the process exited with Windows' Ctrl+C / console-closed status right after Norgate initialised, and nothing reached Alpaca (no orders after 2 pm, state files untouched). The task runs "interactive only", so it pops up a cmd window at 4:30 pm; closing that window kills the run. I re-ran the job by hand at 8:50 pm at below-normal priority. Norgate was answering each price call in 1 to 2 seconds at the time (its updater busy on one core, 2 GB of RAM free with the game running), and the refresh re-pulls full history for about 3,500 names, so the rerun was still fetching at 9:15 pm and should finish before midnight; its orders fill at Tuesday open. Worth fixing: the daily refresh only needs the active names and the last few days, not the full history of every delisted stock. To stop it recurring, `scripts/run_daily_hidden.vbs` launches the same command with no window and unbuffered output; the task needs to be pointed at it, which I am not permitted to do from here. One command, as the user who owns the task:

  ```
  schtasks /change /tn "StockTrader Daily" /tr "wscript.exe //B \"E:\Coding\StockTrader\scripts\run_daily_hidden.vbs\""
  ```

  The old action, for reference: `cmd.exe /c ".venv\Scripts\python.exe scripts\run_daily.py >> data\run_daily.log 2>&1"` starting in `E:\Coding\StockTrader`.
- Two fixes landed this morning: Norgate's renamed delisting tickers (e.g. ROKU-202611) are dropped before ordering, and the broker cancels stale orders and continues past a rejected symbol instead of aborting the run.
- Dry runs (`--dry-run`) no longer touch the live state, equity log or orders log; they only exercise the paper broker.
- Nothing is committed; the working tree holds config, exposure gates, sleeve, fundamentals, books, OPG orders, reconciliation and tests (81 passing). Backups of the pre-switch state are in `data/backup_2026-11-09_0550/`.
- The Sharadar key lives in `.env` (gitignored) as `SHARADAR_API_KEY`. Live loading goes through `src/providers_sharadar.py` with a cache in `data/`; the sweep's bulk download and panel builder stay in the scratchpad.

## 8. Status at 5 am, 2026-11-10

**Paper account switched to the sweep leader.** `config.yaml` now runs `c189f_fcfy30` (consistency-heavy momentum with a 30% free-cash-flow-yield tilt, Sharadar fundamentals), a 3-day rebalance cadence, T-bill yield on idle cash and the IEF/GLD sleeve. Backtest: stitched 26-year Sharpe 1.00, CAGR 10.6%, max drawdown −18% (paper model was 0.79). The rebalance ran at 4:30 am with the regime gates at 29% invested, so the account goes to 28.7% stocks, 34.6% IEF, 34.6% GLD. 71 orders are open for Tuesday's open: 32 buys, 39 sells. Six full exits were first rejected because a notional sell is converted to shares at the broker's current price and overshot the shares held; the broker now liquidates full exits by position (`close_position`), and those six were resubmitted that way. Equity $100,263.

**Sweep is 3x faster.** Profiling one run showed 38% of the time rebuilding the feature index's date level every day, 15% in a per-ticker Python loop in `rebalance`, 16% computing extra features nobody used, and, worst of all, a 4-minute (23 minutes under load) Norgate reload every time a worker switched between the two test windows. All fixed with identical results (max difference 1e-16 on the leader's 2000s window; 81 tests pass): precomputed date sets, vectorised rebalance and benchmark, lazy extra features, both windows cached and resident. Simple variants now finish in under a minute; full stock-picking runs should take 2 to 3 minutes instead of 9. CUDA was considered and rejected: the daily loop is sequential and RAM, not compute, caps the worker count. 32 GB of RAM would double throughput again.

**Queue.** Round 27 (108 runs: SPY controls, tactical asset allocation, hybrids, LightGBM, stop-losses, optimizer sizing) is running; round 28 (untuned universe ranks 451 to 1000, reversal and 1-month books) follows; round 29 (equal-budget honing of every family) queues itself when those finish. About 545 runs remain, roughly 8 to 12 hours at the new speed, then round 29 adds about 5 more.

**Scorecard for choosing between families** (proposed): stitched Sharpe is primary; the 2000s out-of-sample window and the 451 to 1000 universe must beat the SPY-plus-gates control; worst calendar year no worse than −15% and drawdown no worse than −25%; CAGR breaks ties, then simplicity; differences under 0.03 Sharpe are noise. A new leader replaces the paper model only when it clears the live model by 0.03 with the 2000s window not worse.

**Unattended running.** A check-in inside the Claude session runs every 4 hours (sweep health, leaderboard, promote rule, queue depth, daily-job verification) and renews itself weekly. It cannot alert from an offline PC: `scripts/heartbeat.ps1` posts a status line every 10 minutes to a healthchecks-style ping URL stored in `.env` as `HEALTHCHECK_URL`, and the monitor emails when pings stop. Two commands still need the task owner, plus pausing Windows Update for the month (active hours are 8 to 17, so an update could reboot overnight):

  ```
  schtasks /create /tn "StockTrader Heartbeat" /sc minute /mo 10 /f /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File E:\Coding\StockTrader\scripts\heartbeat.ps1"
  schtasks /change /tn "StockTrader Daily" /tr "wscript.exe //B \"E:\Coding\StockTrader\scripts\run_daily_hidden.vbs\""
  ```

### 8.1 Check-in, 4:45 am 2026-11-10

- **Sweep healthy:** 3 workers, 61 results in the last hour (was ~25), 525 runs queued, supervisor alive.
- **No new leader.** The round 27 "hybrid" variants briefly topped the board (stitched Sharpe 1.29) but were an artifact: the sleeve only invests idle cash above the configured cash buffer, so a 67% buffer left 69% of the account in T-bills with 7.5% in the asset-allocation sleeve. Raw Sharpe rewards a cash pile. Those results are quarantined, the sleeve gained a `full` option that makes the buffer a true stock/ETF split, and 36 corrected hybrid runs are queued ahead of round 28. The leaderboard now also shows Sharpe on returns in excess of the T-bill; the live model stays first on both (1.00 raw, 0.84 excess), with the stop-loss family next (0.80 to 0.81 excess at 10 to 13% CAGR).
- **LightGBM family fixed:** all 16 runs had failed because unused 500-day features emptied the training set; the extension now computes only the features a ranker names, and the runs are requeued at the head of the queue.

### 8.2 Check-in, 8:45 am 2026-11-10: aborted switch, sweep contamination found and fixed

- **What happened.** The corrected hybrid family (stock book capped at a third of the account, always-equal SPY/IEF/GLD on the rest) posted a stitched Sharpe of 1.125 and 0.95 on returns in excess of T-bills, and cleared every promotion test. I added the matching `full` sleeve option to `src/sleeve.py` (kept and tested: nine sleeve tests pass), switched `config.yaml` and started the paper switch at 8:41. Before it submitted anything I found that the stock book in those runs earned twice as much per unit of weight as the live model's. Replaying variants exactly as a worker runs them showed why: the sweep workers built their backtest from `config.yaml`, which since the 4:30 switch carries the live IEF/GLD sleeve and cash yield. Every sweep run started after that had the live sleeve underneath the sweep's own sleeve; the hybrids ran with 112% of the account invested. Without the hidden sleeve the hybrid's 2000s Sharpe is 0.96 against 1.06 for the live model. The switch was killed with the account untouched (the 4:30 orders filled at the open as planned) and `config.yaml` is back on the live model.
- **Fix.** The sweep now reads a frozen base config in its own folder, with sleeve, cash yield, fundamentals and books forced off so the extension sets them per variant and nothing in the live config can leak again. The replay harness installs the worker's hook and now reproduces stored results exactly (zero difference on the live model's 2000s window). The 291 results produced since 4:00 (corrected hybrids, round 28, the round-29 honing so far, including a half-sleeve variant that showed 1.33) are quarantined and requeued at the head of the queue; 108 old queue files written against the original base were parked. Queue 861, supervisor relaunched with 4 workers.
- **Rule change.** A candidate is promoted only after an exact replay reproduces its stored result and its daily series shows stocks plus sleeve plus cash at or under 100%. Raw Sharpe with cash yield also rewards T-bill piles, so excess Sharpe and CAGR are read together.

### 8.3 Check-in, 12:45 pm to 5:10 pm 2026-11-10: new leader on liquidity ranks 451 to 1000, paper account switched

- **Clean redo.** The 291 quarantined runs were repeated on the frozen base. The corrected hybrids are not leaders once cash is accounted for (half-book 1.04 raw Sharpe but 0.84 over T-bills at 9.2% CAGR). Stop-losses, asset-allocation engines, LightGBM rankers and optimizer sizing all finish below the previous live model; optimizer sizing is a dead end (0.35 to 0.49 excess Sharpe, 40% drawdowns). The previous live model re-expressed in the sweep harness reproduces its stored 2000s Sharpe exactly, which shows the redo is clean.
- **New leader.** The earnings ranker (earnings surprise and free-cash-flow yield, 50/50) run on liquidity ranks 451 to 1000 with 40 names and the unchanged stack (inverse-volatility sizing, equal sectors, 3-day rebalance, market gates, IEF/GLD sleeve):

  | | Stitched Sharpe | Excess over T-bills | 2000s OOS | 2010 on | CAGR | Max DD | Worst year |
  |---|---|---|---|---|---|---|---|
  | New: `sue_fcfy`, ranks 451 to 1000, top 40 | 1.060 | 0.890 | 1.240 | 0.945 | 11.1% | −18.6% | −9.1% (2022) |
  | Previous: `c189f_fcfy30`, top 450, top 55 | 1.003 | 0.836 | 1.062 | 0.964 | 10.6% | −18.0% | −10.6% (2022) |
  | SPY with the same gates and sleeve | 0.885 | 0.713 | 0.722 | 0.989 | 9.0% | −21.1% | −14.6% (2022) |

  The band was built as a robustness universe that no setup had been tuned on. The band alone is not the edge: the previous leader's ranker scores 0.94 there and plain momentum 0.71. The earnings ranker scores 0.99 on the top 450 and 1.06 on the band, consistent with earnings surprises being priced in more slowly in less-followed names. Every variant of it run so far beats the previous live model on excess Sharpe (55 or 70 names, 2-, 5- and 10-day rebalance, cooldowns, volatility targets: 0.85 to 0.90).
- **Checks before the switch.** Both windows replay with zero difference from the stored daily series. Stocks held at the prior close plus the sleeve never exceed 98% of the account (the sleeve column is lagged a day, so adding it to same-day stock weights wrongly shows days above 100%; the previous live model shows the same pattern). The live Sharadar features match the sweep's panels cell for cell (2 differing cells in 1.18 million).
- **Code.** `data.liquidity_band: [lo, hi]` restricts ranking to ranks lo+1 to hi of the top-hi universe while the exposure gates keep reading the whole universe (`src/universe.trade_membership`, used by both scripts). Ranker preset `sue_fcfy` added. 84 tests pass.
- **Switch.** Dry run at 1:44 pm: 40 names, 31% stocks. The first real run died in a system crash at 1:57 pm (Windows bugcheck 0x9F, a device driver power-state failure, unrelated to the sweep) before submitting anything; Alpaca confirmed no orders. The scheduled 4:30 pm job then held as designed ("Not a rebalance day"). The switch was rerun on today's close and finished at 5:07 pm: 98 orders accepted for the 2026-11-11 open, none rejected, targets 31.3% stocks (40 names), 33.4% IEF, 33.4% GLD, 2% cash. Next scheduled rebalance 2026-11-13.
- **Not yet promoted.** Three honing variants score above the new model: a 20% sector cap in place of the equal split (1.12 stitched, 0.96 excess, 12.3% CAGR), no sector rule (1.10, 0.93) and daily rebalancing (1.09, 0.92; the 2-day cadence is the worst of five). With about 25 knobs tried, the best of them is expected to sit around 0.06 above the base by selection alone, so these are leads, not results. An 84-run confirmation round is at the head of the queue: sector caps of 15 to 40%, name counts, cadence crosses, band lower edges of 200, 300 and 600, the whole top 1000, and earnings-surprise freshness windows of 21 and 42 days (the 63-day window is identical to the plain signal because filings are quarterly). The sector cap exists only in the sweep extension; it gets ported to `src` if the round confirms it.
- **Operations.** The sweep was stopped at 12:25 pm by a timer I had left armed in the morning, was relaunched at 12:47, paused for the switch and lost in the crash; relaunched at 5:08 pm with 614 runs queued. `start_sweep.ps1` in the sweep folder now restarts it after a reboot (requeues orphaned runs, clears the stop file, launches the supervisor).

### 8.4 Check-in, 8:45 pm 2026-11-10 to 4:30 am 2026-11-11: sector cap promoted, daily job memory bug found and fixed

- **Confirmation round.** The 84-run round queued at 5 pm finished. A sector cap in place of the equal sector split holds up across its neighbours on the live ranker (band 451 to 1000, 40 names):

  | Sector rule | Stitched Sharpe | Excess over T-bills | 2000s OOS | 2010 on | CAGR | Max DD | Worst year |
  |---|---|---|---|---|---|---|---|
  | Equal split (previous live) | 1.060 | 0.890 | 1.240 | 0.945 | 11.1% | −18.6% | −9.1% |
  | Cap 15% (6 names per sector) | 1.073 | 0.908 | 1.268 | 0.951 | 11.6% | −18.3% | −10.1% |
  | Cap 20% (8) | 1.123 | 0.959 | 1.315 | 1.003 | 12.3% | −18.3% | −9.9% |
  | **Cap 25% (10), now live** | **1.127** | **0.963** | **1.296** | **1.023** | **12.3%** | **−18.8%** | **−10.2%** |
  | Cap 30% (12) | 1.110 | 0.947 | 1.253 | 1.023 | 12.2% | −18.6% | −10.2% |
  | Cap 40% (16) | 1.091 | 0.928 | 1.236 | 1.003 | 11.9% | −18.6% | −10.2% |
  | No sector rule | 1.095 | 0.932 | 1.241 | 1.006 | 12.0% | −18.6% | −10.2% |

  The response is a smooth hump with a plateau from 20 to 30%, and the gain shows in both windows. With the 20% cap it survives a 5% weight cap (1.119), volatility targets of 12 and 20 (1.120, 1.119), a 5-day cooldown (1.108), band lower edges of 200 and 300 (1.130, 1.121) and the whole top 1000 (1.114). 25% is the centre of the plateau, so that is the value promoted; 20% sits next to the drop at 15%.
- **Other findings from the round.** Daily rebalancing on top of the cap adds nothing (1.127), and the 2-day and 5-day cadences are worse (1.094, 1.092), so cadence stays at 3 days. Name count is sensitive: with the 20% cap, 30 / 40 / 55 / 70 names score 1.047 / 1.123 / 1.071 / 1.071. Earnings-surprise freshness windows of 21 and 42 days are identical to the plain signal on every run, so there is no evidence that reacting faster to filings helps at this cadence. With the cap in place the band's lower edge barely matters between 0 and 450 (1.114 to 1.130) and falls off at 600 (1.018); the whole top 1000 with 70 names and a 20% cap scored 1.139, a lead for the next round rather than a result.
- **Checks before the switch.** Both windows of the 25% cap replay with zero difference from the stored series. Stocks at the prior close plus the sleeve peak at 98.1%. The cap was sweep-only code: it is now `portfolio.sector_mode: "cap"` with `portfolio.sector_cap` in `src/portfolio.py`, and it picks exactly the sweep's names in 4,000 randomised comparisons.
- **The daily job was freezing the PC.** `run_daily.py` built features for every ticker Norgate returns since 2010 (11,955), where the sweep first drops names that were never in the universe (3,058 remain). The untrimmed job needed more memory than the 6 to 8 GB usually free. It got through on 2026-11-10 with 12 GB free; the evening dry run took 73 minutes while Windows services timed out, most likely the same thrashing; and at 3:28 am on 2026-11-11 took free memory from 6 GB to under 1 GB in a minute; the machine locked up and was power-cycled. Nothing reached Alpaca in any of the failed attempts. Three changes:
  - `src/universe.trim_to_universe` is applied in `run_daily.py` and `run_backtest.py`. Peak memory is now about 5 to 6 GB and a full run takes 11 minutes. It is also a fidelity fix: percentile ranks and median fills are taken over the columns present, so the live job had been ranking against a wider set than the backtests. The trimmed run picks 38 of the same 40 names as the untrimmed one.
  - `src/memguard.py`: a small watcher process stops the daily job if free memory falls below `live.min_free_gb` (1 GB). It is switched off before the job contacts the broker, so a run is never cut off while sending orders.
  - The sweep supervisor now stops its workers while a `run_daily` process exists and on weekdays from 16:24 to 16:35, and restarts them afterwards. The sweep runs 3 workers instead of 4.
- **Switch.** Real run at 4:08 am on the 2026-11-10 close, 11 minutes, memory floor 3.3 GB: the 98 orders queued at 5:07 pm were cancelled and replaced. Targets are 40 names at 31.3% (Financials at the 10-name cap), IEF 33.4%, GLD 33.4%, cash 2%. Two full exits (VMRK, AEP) were rejected because Alpaca had not finished releasing the shares held by the cancelled orders; they were resubmitted by hand together with an $0.84 leftover in STT, giving 99 open orders for the 2026-11-11 open. `AlpacaBroker.submit_targets` now waits until no order is open after cancelling. The state file was rebuilt from the account's actual holdings before the run, so no name carries a cooldown it did not earn. Next scheduled rebalance 2026-11-13.
- **Interruptions.** The session dropped at 10:04 pm because the Claude desktop app updated itself and restarted, which killed a run five seconds in. Long runs are now launched detached with a memory log. The sweep was paused from 10:24 pm to 4:30 am at the user's request.
- **Queue.** A 104-run honing round around the capped model is at the head of the queue: finer cap grid and an industry-group cap, 30 to 55 names, cadence, cooldown, minimum trade, exit bands, sizing, a 20% third factor (eight candidates), band edges, and the whole top 1000 with 40 to 100 names. 94 tests pass.

### 8.5 Check-in, 8:45 am 2026-11-11: fills confirmed, honing round finished, daily rebalancing under test

- **Fills.** All 99 orders filled between 8:30 and 8:35 am, none rejected, none left open, no symbol twice. The account holds 40 stocks at 31.3%, IEF 33.5%, GLD 33.3% and 2% cash; equity $99,768.
- **Honing round (104 runs) finished, no promotion.** Almost everything around the live model lands at or below its 1.127: cap 22.5% / 27.5% / 35% score 1.129 / 1.125 / 1.106, 30 to 55 names 1.044 to 1.119 (40 remains a spike), cooldown 0 / 5 / 20 days 1.124 / 1.123 / 1.106, minimum trade 10% / 30% 1.117 / 1.130, exit bands 1.109 and 1.095, equal and rank sizing 1.085 and 1.041, every third factor 1.029 to 1.119, band lower edge 200 / 300 / 600 1.134 / 1.135 / 1.017. Removing the sleeve costs 0.06 and the cash yield 0.004.
- **Three results reach the promote margin of 1.157 or come within 0.003 of it, and none is promoted yet.**

  | Variant | Stitched | Excess | 2000s OOS | 2010+ | CAGR | Max DD | Worst year |
  |---|---|---|---|---|---|---|---|
  | Live: band, 40 names, 25% cap, 3-day cadence | 1.127 | 0.963 | 1.296 | 1.023 | 12.3% | −18.8% | −10.2% |
  | Same, daily cadence | 1.161 | 0.996 | 1.293 | 1.080 | 12.7% | −17.7% | −10.0% |
  | Whole top 1000, 55 names, 25% cap | 1.156 | 0.990 | 1.271 | 1.084 | 12.5% | −17.7% | −9.4% |
  | Whole top 1000, 70 names, 25% cap | 1.154 | 0.986 | 1.276 | 1.077 | 12.4% | −18.0% | −8.4% |

  The daily cadence clears the margin by 0.004, but its 2000s window is 0.003 below the live model's, it is a single knob, and the cadence response is not smooth: 1 / 2 / 3 / 4 / 5 days score 1.161 / 1.106 / 1.127 / 1.041 / 1.056. With the 20% cap, daily cadence added nothing (1.127 against 1.123). A zig-zag like that is what schedule-phase luck looks like: a 3-day schedule can start on any of three days, and the backtest only ever tested one of them. The two whole-universe results miss on the 2000s window.
- **Confirmation round queued (88 runs, ahead of the ML queue).** A new sweep key shifts the rebalance schedule by N days, so every phase of the 2-, 3-, 4- and 5-day cadences is now run. That gives the phase spread, which is the real noise on the live 1.127 and the fair comparison for the daily cadence. Daily cadence is also rerun across caps, name counts, minimum trade, cooldown, exit band, band edges, volatility targets and without the sleeve; the whole-universe variants get their phases, a daily run and neighbours at 60 / 65 / 80 names.

### 8.6 Check-in, 11 am 2026-11-11: daily rebalancing promoted; take-profit and stop-loss rules tested and rejected

- **The schedule's start day matters more than the promote margin.** A 3-day schedule can start on any of three days; every backtest so far used the first. On the live model the three score 1.127, 1.092 and 1.063 stitched, so the live figure was the luckiest of the three and the fair figure is their mean, 1.094 (2000s window: 1.296, 1.214, 1.233, mean 1.248). A run with the same phase started three days later reproduces 1.127, which shows the spread comes from the schedule and not from the start date. Averaged over start days, faster is steadily better: 1 / 2 / 3 / 4 / 5 days score 1.161 / 1.119 / 1.094 / 1.088 / 1.073. The zig-zag reported in 8.5 was phase luck. A daily schedule has no start day to be lucky about.
- **Daily rebalancing confirmed.** In 25 of 25 neighbouring setups the daily version scored at least as well as its 3-day twin (caps 20 to 30%, 35 to 50 names, minimum trade 10 and 30%, cooldown 0 / 5 / 20, exit band, band edges 200 and 300, volatility targets 12 and 20, 5% weight cap, a third factor, no sleeve, no cash yield, equal-sector and no sector rule, and the whole top 1000 with 55 and 70 names), typically by about 0.03, and those twins all use the lucky start day. Year by year it beats the 3-day mean in 21 of 26 years.

  | Variant | Stitched | Excess | 2000s OOS | 2010+ | CAGR | Max DD | Worst year |
  |---|---|---|---|---|---|---|---|
  | 3-day, mean of the three start days | 1.094 | n/a | 1.248 | n/a | 11.9% | n/a | n/a |
  | 3-day, start day 0 (the old live figure) | 1.127 | 0.963 | 1.296 | 1.023 | 12.3% | −18.8% | −10.2% |
  | **Daily (promoted)** | **1.161** | 0.996 | 1.293 | 1.080 | 12.7% | −17.7% | −10.0% |

  On the promote rule: the stitched margin is met against either baseline. The 2000s window is 0.003 below the start-day-0 figure and 0.045 above the mean of the start days; the live account's start day is arbitrary, so the mean is the comparison used.
- **Trading cost is the risk, and it was stressed.** Daily trades 18 times the portfolio a year against 14 (2010 on; 14 against 11 in the 2000s), which is 1.80% against 1.39% a year at the assumed 10 bps per trade. The cost floor binds on every trade in these runs, so other cost levels follow exactly from the stored turnover:

  | Cost per trade | 0 bps | 5 | 10 | 15 | 20 | 30 |
  |---|---|---|---|---|---|---|
  | Daily | 1.315 | 1.238 | 1.161 | 1.084 | 1.007 | 0.853 |
  | 3-day, mean of start days | 1.213 | 1.153 | 1.094 | 1.035 | 0.976 | 0.857 |
  | Difference | +0.102 | +0.085 | +0.067 | +0.049 | +0.031 | −0.004 |

  The advantage survives a doubling of the assumed cost and disappears near 30 bps. Thirty-six queued runs repeat this through the backtest itself, and the morning's 99 fills will be compared with the official opens once the bars are in.
- **Checks.** Both windows of the daily candidate replay with zero difference from the stored series. Stocks at the prior close plus the sleeve peak at 98.0%. No new code is needed for the model: `portfolio.rebalance_every_days` goes from 3 to 1.
- **Switch.** No forced run: orders sent during market hours would fill at once and not at the next open. The scheduled 4:30 pm job on 2026-11-11 makes the change itself, since with a 1-day cadence every run with a new closing bar is a rebalance. `run_daily.py` now also holds when the data has no new bar since the last rebalance, so a late data update cannot cause a second trade on the same close. 95 tests pass.
- **Take-profit and stop-loss rules (134 runs, 67 rules).** New sweep rule measured from the price on the day a stock was picked: sell after a set gain, a set loss, or a set fall from the high since purchase, optionally with a re-buy block. None helps. On the 3-day schedule the best are a 50% or 20% take profit at 1.140 and a 25% stop at 1.132, inside the noise shown above; tighter is steadily worse (take profit 10% / 5% / 3%: 1.079 / 1.062 / 0.987; stop 10% / 5% / 2%: 1.089 / 1.066 / 0.973; trailing 10% / 5% / 3%: 1.046 / 0.962 / 0.811; a 5% gain with a 3% loss: 0.810). Checked daily, every rule scores at or below plain daily rebalancing (30% take profit 1.151, 8% stop 1.104, 5% trailing stop 0.884). The older rolling-high stops score 0.983 to 1.077. The ranking already sells a stock when its earnings surprise and cash-flow yield stop ranking well; a price rule on top sells winners that still rank well and then buys them back.
- **Leads, queued (54 runs).** With daily rebalancing the whole top 1000 with 55 names scores 1.195 (2010+ 1.160) but 1.251 in the 2000s, which fails the 2000s condition; a band starting at rank 200 scores 1.181 with 1.319 in the 2000s; a 30% and 40% minimum trade score 1.170 and 1.173 and trade less. Each is within 0.035 of the promoted model and gets a neighbour round before any decision.

### 8.7 Check-in, 12:45 pm 2026-11-11: cost stress confirmed by full runs; a wider band looks better and is being confirmed

**Health.** Three workers and the supervisor are up, nothing failed, 1,911 results, 5.8 GB of memory free. Two workers are on slow machine-learning runs, so the quick runs go through one worker for now.

**Cost stress (round 34, 36 runs).** The full backtests reproduce the figures worked out by hand in 8.6 to three decimals:

| Cost per trade | 15 bps | 20 bps | 30 bps |
|---|---|---|---|
| Daily | 1.084 | 1.007 | 0.853 |
| 3-day, average of start days | 1.035 | 0.975 | 0.857 |

Doubling the market-impact coefficient or the spread changes nothing, because the 10 bps floor is what every trade pays in these backtests.

**Neighbours of the daily model (round 34, 54 runs).** Live model: 1.161 stitched, 1.293 in the 2000s, 12.7% CAGR.

| Setup (all daily, 25% sector cap) | Stitched | 2000s | 2010+ | CAGR | Max drawdown | Trades per year |
|---|---|---|---|---|---|---|
| Live: ranks 451-1000, 40 names | 1.161 | 1.293 | 1.080 | 12.7% | -17.7% | 16.5x |
| Ranks 201-1000, 40 names | 1.181 | 1.319 | 1.095 | 12.9% | -16.8% | 15.3x |
| Ranks 201-1000, 45 names | 1.198 | 1.303 | 1.132 | 13.0% | -17.1% | 14.9x |
| Ranks 201-1000, 50 names | 1.190 | 1.295 | 1.125 | 12.9% | -17.2% | 14.7x |
| Ranks 101-1000, 55 names | 1.201 | 1.321 | 1.125 | 13.0% | -17.3% | 14.1x |
| Whole top 1000, 55 names | 1.195 | 1.251 | 1.160 | 12.9% | -16.9% | 13.6x |
| Live with a 40% no-trade band | 1.173 | 1.294 | 1.098 | 12.6% | -17.8% | 14.7x |
| Live with an 80% no-trade band | 1.209 | 1.439 | 1.062 | 11.9% | -17.0% | 11.0x |

- **Wider band, more names.** Starting the band at rank 101 to 251 and holding 45 to 55 names scores 1.18 to 1.20 across eight runs, with lower turnover. Four of them clear the promote rule on paper, by 0.035 to 0.040. That is inside the range where I require a confirmation round, and the four differ from each other only by noise, so nothing was promoted.
- **Wider no-trade band.** The score rises steadily as positions are resized less often, but most of that is not a trading saving. A wide band also stops the stock book from growing back after the risk gates reopen, so the bond/gold share rises from 33% to 46% and CAGR falls to 11.9%. It is a quieter portfolio, not a better stock picker.
- **Whole top 1000.** Still fails the 2000s condition (1.24 to 1.27 against 1.293).

**Queued (round 35, 122 runs).**
- The full grid of band start (rank 101 to 301) against 40 to 60 names, plus sector cap and no-trade band around the best points.
- Robustness of ranks 201-1000 with 45 names: 20 bps cost, re-buy cooldown, 2- and 3-day schedules at every start day, equal sizing, no bond/gold sleeve.
- A new resize rule that separates the two effects above: a position is left alone while its own drift is small, but the whole book is rescaled when the risk budget moves by more than 5, 10 or 20%. The sweep code for it passed a 400-case check against the existing rule.

If the grid is smooth I will promote the centre of the plateau, not its highest point. It would be a two-number config change.


### 8.8 Wednesday 2026-11-11, mid afternoon: wider band promoted (ranks 201-1000, 45 names)

**Round 35 (122 runs) confirmed the plateau.** Stitched Sharpe, all daily with a 25% sector cap (live 1.161):

| Band starts after rank | 40 names | 45 | 50 | 55 | 60 |
|---|---|---|---|---|---|
| 100 | 1.144 | 1.164 | 1.202 | 1.201 | 1.178 |
| 150 | 1.144 | 1.184 | 1.201 | 1.185 | 1.171 |
| 200 | 1.181 | **1.198** | 1.190 | 1.187 | 1.183 |
| 250 | 1.180 | 1.194 | 1.188 | 1.169 | 1.180 |
| 300 | 1.169 | 1.181 | 1.189 | 1.193 | 1.157 |

Every cell from 45 to 55 names beats the live model, and the surface is smooth.

**Promoted: ranks 201-1000 with 45 names.** This was the setup chosen before the round for the full robustness battery, and it sits in the middle of the plateau. The neighbouring 50-name cell is 1.190, within noise of it.

| Check | Candidate | Live (ranks 451-1000, 40) |
|---|---|---|
| Stitched Sharpe 2001-2026 | 1.198 | 1.161 |
| Over T-bills | 1.032 | 0.996 |
| 2000s out of sample | 1.303 | 1.293 |
| 2010+ | 1.132 | 1.080 |
| CAGR | 13.0% | 12.7% |
| Max drawdown | -17.1% | -17.7% |
| Worst year | -8.9% (2022) | -10.0% (2022) |
| Turnover | 14.9x a year | 16.5x |
| At 20 bps a trade | 1.058 | 1.007 |
| 2-day schedule, mean of start days | 1.160 | 1.119 |
| 3-day schedule, mean of start days | 1.133 | 1.094 |
| SPY + gates + sleeve control | - | 0.885 |

- **Exact replay:** both windows reproduce the stored daily series with zero difference.
- **Budget:** stocks held the day before plus the bond/gold weight peak at 98.0%, never over 100%.
- **Re-buy cooldown:** 5 or 20 days give 1.203 and 1.205, so the setting is not fragile.
- **Year by year:** it beats the live model in 13 of 26 years, by 0.3 points a year on average. The gain is broad but small, as expected from a 0.04 Sharpe improvement.

The change is two numbers in config.yaml: `data.liquidity_band: [200, 1000]` and `portfolio.top_n: 45`. The sector cap of 25% now allows 11 names per sector. It takes effect at the 16:30 scheduled job; there was no forced run during market hours.

**Also read in round 35.**
- **Resize rule** (leave a position alone while its own drift is small, rescale the book when the risk budget moves). The "same as today" setting reproduces the live model exactly (1.161). The best setting, 40% drift with a 20% budget band, scores 1.179, inside noise. Never resizing on own drift is clearly worse (1.06 to 1.11). Not adopted.
- **Re-buy cooldown on the live model:** 0, 5 and 20 days give 1.153, 1.157 and 1.148 against 1.161 for 10 days, so it stays at 10.
- **Wider no-trade band on the new setup:** a 40-50% band scores 1.209-1.213 but again shifts money into bonds and gold. Not adopted, for the reason given in 8.7.

**Since 8.7.**
- 316 queued tuning runs of the old top-450 momentum model were parked; their untested settings were moved onto the live model (round 37).
- Rounds 38 (value, improving fundamentals, quality, an announcement-day surprise proxy, lottery stocks, overnight returns, calendar rules), 39 and 40 (factor momentum, sector-neutral ranks, regime switching, dip buying, decorrelation, lead-lag, pairs, sector-ETF rotation, risk parity, seasonality, market-cap sizing, fixed stock/bond splits and more) are built, tested and queued, about 500 runs.
- **Blending whole models** (362,701 pairs and triples of the 40 most distinct models) does not beat the live model out of sample. A blend chosen on 2011+ scores 0.990 over T-bills in the 2000s, against 1.097 for the live model. The best in-sample blends mostly add bonds and gold.
- **Staggered sub-portfolios** (2- to 5-day schedules, all start days averaged) never beat daily rebalancing, even at 20 bps.


### 8.9 Wednesday 2026-11-11, 16:45: first run of the new model; real trading costs measured

- **Scheduled job (16:30):** clean. Data as of 2026-11-11, 45 positions from ranks 201-1000, exposure 0.32 (31.7% stocks, 66.3% IEF/GLD), 48 market orders for the next open (20 buys, 28 sells). No symbol has two orders, every dropped name has a sell, every new name has a buy, and nothing was rejected. The sweep paused its workers from 16:24 to 16:40 as designed.
- **Real fill costs (scripts/reconcile_fills.py, 224 fills, 9-11 November):** slippage against the official open averaged 9.6 bps weighted by size (median 0, mean 14.2), and 98% of orders filled within five minutes of the open. The backtests charge 10 bps a trade, so the cost assumption holds and the ranking of models stands.
- **No new leader.** The best new-base result is a 5-day breadth gate at 1.225 stitched, under the 1.228 the rule needs, with a weaker 2000s score (1.230 against 1.303).
- **Vol lookback not testable yet.** The backtest computes inverse-vol sizing on a fixed 20-day window (src/backtest.py), so the 10/40/60-day runs came out identical to the live model. Live trading reads the same 20 days from config.yaml, so live and backtest agree. Wiring the setting into the backtest is on the optimization list.


### 8.10 Thursday 2026-11-12, 00:15: restart, strong signals, round 42

- **PC restart 22:25-22:33.** Windows logged an unexpected shutdown with no crash code and a power-button press; the pagefile peaked at 826 MB, so memory was not the cause. The sweep does not restart itself after a reboot; it was relaunched at 00:11 (about 1.5 hours lost, three interrupted runs requeued). Registering sweep/start_sweep.ps1 as a logon task would make this automatic.
- **Rounds 37-39 are complete on the new model.** Five changes clear the promote margin (live 1.198, so 1.228 is needed):

| Change on the live model | Stitched | Over T-bills | 2000s | CAGR |
|---|---|---|---|---|
| + 20% revenue surprise | 1.259 | 1.093 | 1.434 | 13.7% |
| Universe ranks 201-1500 | 1.259 | 1.096 | 1.430 | 14.0% |
| + 20% EBITDA/EV | 1.242 | 1.078 | 1.410 | 13.7% |
| + 20% sales/price | 1.234 | 1.073 | 1.437 | 13.8% |
| + 20% operating profitability | 1.234 | 1.067 | 1.433 | 13.4% |

  Alone, the same signals score only 0.94-1.03: they help as partners, not as strategies. About 200 variants have run on this base, so the best is expected to be around 0.06 above it by chance, which is where these sit. They go to a confirmation and combination round, not straight to the account. Ranks 201-750 score 1.170, so the gain is from adding the less liquid names, not from any band shape.
- **Did not help (rounds 38-39 on the new model):** factor momentum (0.82-1.15), regime-switched rankings (0.97-1.14), sector-neutral ranks (1.06-1.15), score smoothing (1.04-1.14), buying on dips (1.13-1.17), the announcement-premium proxy (0.86-1.07), the strategy-equity gate (1.07-1.15). The member-rank control scores 1.179.
- **Round 42 (270 runs):** every 2-, 3- and 4-signal combination of revenue surprise, EBITDA/EV, sales/price, operating profitability, ROIC and F-score at 20% and 40% of the ranking; each top signal at other weights; universe neighbours (201-1250 / 1500 / 2000, other edges and book sizes); pairs of the strong rules; combinations of signals with the wider universe. Strong results from rounds 40-41 join in round 43.


### 8.11 Thursday 2026-11-12, 09:45: new leader, the quality/value tilt (round 42)

- **Promoted:** `model.type: sue_fcfy_q6`. It keeps 80% of the live ranking (earnings surprise + free-cash-flow yield) and splits the other 20% equally over six signals: revenue surprise, EBITDA/EV, sales/price, operating profitability, ROIC and the Piotroski F-score. Everything else is unchanged (ranks 201-1000, 45 names, 25% sector cap, daily rebalance, IEF/GLD sleeve). It takes effect at the 16:30 scheduled job; there was no forced run during market hours.

| | Stitched | Over T-bills | 2000s | 2010+ | CAGR | Max DD | Worst year |
|---|---|---|---|---|---|---|---|
| Live until today | 1.198 | 1.032 | 1.303 | 1.132 | 13.0% | -17.1% | -8.9% |
| sue_fcfy_q6 | 1.264 | 1.097 | 1.470 | 1.136 | 13.8% | -16.9% | -8.4% |

- **Why this one and not the top score.** Round 42 tried every 2-, 3- and 4-signal subset of the six at 20% and 40%. Nearly every 20% subset beats the live model (1.20 to 1.28 stitched), and the 40% versions are weaker, so a modest tilt is the robust finding. The best single subset (EBITDA/EV + sales/price + operating profitability + ROIC, 1.280) is within noise of the others; picking it would mostly be picking luck. The all-six version needs no choice among subsets and sits in the middle of that plateau. At 30% and 40% it scores 1.262 and 1.252.
- **Checks:** beats the live model in 19 of 26 years (by 0.7 points a year on average; worst year -3.8 points, 2021). Exact replay matches the stored run to the last digit. Stocks plus sleeve never exceed 100% (peak 98%).
- **Port to the live code:** the six signals existed only in the research sweep. They are now in src/fundamentals.py with definitions identical to the sweep's: 281 random companies matched on every daily value. The quarterly cache was refetched once with the 11 extra Sharadar columns it needs (518,253 rows, 9,484 tickers, 3.6 minutes). An old cache without them is refetched automatically. New unit tests check the definitions; 97 tests pass.
- **Dry run (data to 2026-11-11):** 45 positions, 53 orders, estimated cost 1.0 bps, exposure 0.32 (31.7% stocks, 66.3% IEF/GLD). The daily job now peaks at 7.2 GB instead of 5-6 GB; the lowest free memory during the run was 4.2 GB.
- **Also from rounds 40-41 (on the old ranker):**
  - Strong but not adopted yet: an IEF/GLD sleeve weighted by risk parity (1.250, but 12.7% CAGR); buying new names only within 21 days of a filing (1.234); square-root-of-market-cap sizing (1.222); an Altman-Z distress screen (1.214); a 14-day minimum hold (1.213).
  - Combinations of all of these are queued in round 43.
  - "Combine everything" rankings, trend screens, macro betas, sector rotation and ML ranking targets all scored below the live model.


### 8.12 Thursday 2026-11-12, 15:00: new leader, the same model on ranks 201-1500 (rounds 42 and 44)

- **Promoted:** `data.liquidity_top_k: 1500` and `data.liquidity_band: [200, 1500]`. The ranking, the 45 names and every other setting are unchanged; only the universe grows by the next 500 most-traded stocks. It takes effect at the 16:30 scheduled job (no forced run during market hours).

| | Stitched | Over T-bills | 2000s | 2010+ | CAGR | Max DD | Worst year |
|---|---|---|---|---|---|---|---|
| Live since this morning (ranks 201-1000) | 1.264 | 1.097 | 1.470 | 1.136 | 13.8% | -16.9% | -8.4% |
| Ranks 201-1500 | 1.404 | 1.240 | 1.638 | 1.260 | 15.7% | -17.5% | -7.1% |

- **Not a lone knob.** Wider is better at every step on this ranking (201-1250: 1.358, 201-1500: 1.404, 201-2000: 1.466) and on the old one (1.256 / 1.259 / 1.297 against 1.198).
- **Costs.** The backtest's impact model barely charges small stocks at a $100k account (the 10 bps floor dominates: doubling the impact or the spread changes nothing), so the test that matters is a flat cost per trade:

| Cost per trade | 201-1000 | 201-1500 |
|---|---|---|
| 10 bps (live fills so far: 9.6) | 1.264 | 1.404 |
| 20 bps | 1.124 | 1.276 |
| 30 bps | 0.985 | 1.149 |

  Even at double the cost on every trade it matches the 201-1000 model at today's cost.
- **Checks:** exact replay matches the stored run to the last digit. Stocks plus sleeve never exceed 100% (peak 98%). 99 tests pass.
- **The daily job needed two fixes first.**
  - Memory: the first dry run on 1,500 names passed 10 GB and was stopped by the memory guard. The job now computes features on the last 400 trading days instead of the whole history (live.feature_window_days, default 400). A ranking that scores each day on its own only needs today's row. On the real data, today's features match the full history to within float rounding, with identical scores and identical picks. The job now peaks at 4.7 GB on 1,500 names, against 7.2 GB before on 1,000.
  - Network: a reset connection to Sharadar crashed the second dry run. Requests now retry dropped connections, timeouts, 429 and 5xx (waits of 5, 15, 45 and 120 s).
- **Dry run (data to 2026-11-11):** 45 positions, 49 orders, estimated cost 3.2 bps, exposure 0.33 (32.0% stocks, 66.0% IEF/GLD), lowest free memory 6.3 GB.
- **Round 43 (old ranker):** combinations of the round 40-41 knobs.
  - Best: risk-parity sleeve + 21-day fresh entry + square-root sizing (1.327), risk parity + summer de-risking (1.325), risk parity + fresh entry (1.290). These are retested on the new model in round 44.
- **Next:**
  - Round 45 measures next-open execution. The backtest trades at the decision close, but live orders fill at the next open, so it removes the overnight move from every trade.
  - Then the 201-2000 universe (its cost runs are queued).


### 8.13 Thursday 2026-11-12, 15:07: the ranks 201-1500 switch is reverted (look-ahead in the research data)

- **What was wrong.** The research sweep's fundamentals panels were built only for stocks that were ever in the top 1000 by liquidity at some point between 2000 and 2026.
  - In a top-1000 backtest that is harmless, because every member is in that set.
  - In a wider universe it is look-ahead. A stock ranked 1,200 in 2005 had earnings and cash-flow data only if it later grew into the top 1000. Stocks that stayed small or failed got a neutral score and were almost never bought.
  - The 201-1500 dataset has 4,343 stocks; only 2,308 of them had fundamentals.
  - The "wider is better at every step" pattern in section 8.12 is therefore not trustworthy, and neither are the earlier wider-universe results (round 37 ranks to 1500, round 42 universe and cross runs, round 43 crosses with 201-1500).
- **The live job was never affected the same way.** It loads fundamentals for every name, so the account would have traded a model different from the one backtested. Hence the revert before it ever traded: the account stays on sue_fcfy_q6, ranks 201-1000 (section 8.11). The memory fix and the Sharadar retries from 8.12 are kept; the windowed features were checked exact on ranks 201-1000.
- **Fix in progress.** All fundamentals panels are being rebuilt for every one of the 16,853 Norgate names. The Sharadar extract already holds all 17,079 tickers; only the name list was restricted. The new panels are checked against the old ones on the top-1000 names, then every wider-universe test is rerun.


### 8.14 Thursday 2026-11-12, 17:40: complete fundamentals panels; first clean results of round 46

- **Daily job (16:30):** clean on ranks 201-1000. It used 17 features on the new 400-day window, a 32% stock budget, and placed 51 orders for the 11-13 open. No symbol was ordered twice, every dropped name has a sell and every new name has a buy.
- **Panels rebuilt for every name.** The 43 fundamentals panels now cover 12,158 names, up from 3,065.
  - On the 3,065 old names every value is identical (43 of 43 panels, zero difference, nothing gained or lost), so all ranks 201-1000 results stand.
  - Point-in-time coverage of the wide universes, 2000-2010: the share of priced names with a cash-flow yield rises from 43-53% to 76-79%. That is in line with the live 1000-name cross-section (59% with a current earnings surprise).
- **Wide universes requeued on the complete panels.** 66 variants are queued after round 46:
  - first the universe ladder 201-1250 / 1500 / 1750 / 2000 / 2500 / 3000;
  - then their 20/30 bps and next-open checks;
  - then every parked combination.
  
  The 33 contaminated results are moved out of the leaderboard (sweep results_lookahead/).
- **Next-open execution (round 45), ranks 201-1000:** filling at the next open instead of the decision close lowers the live model from 1.264 to 1.226. The timing gap is small.
- **Round 46: the round 43 rules on the live ranker, ranks 201-1000.** Each rule alone, against the live 1.264:

  | Rule | Stitched | 2000s |
  |---|---|---|
  | IEF/GLD sleeve by risk parity | 1.323 | 1.644 |
  | Summer de-risking (May-Oct x0.75) | 1.307 | 1.544 |
  | New names only within 21 days of a filing | 1.299 | 1.464 |
  | Square-root market-cap sizing | 1.283 | 1.519 |
  | Altman Z >= 1.81 screen | 1.282 | 1.473 |
  | Minimum hold 14 days | 1.273 | 1.460 |

  On the old ranker the combination of risk parity, fresh entry, square-root sizing and the Z screen scored 1.330, and 1.369 with revenue surprise. Not promoted yet, for three reasons:
  - these are single-rule results;
  - the combinations, cost and next-open runs are still queued;
  - none of the rules exist in the live code yet. Each needs a port and a test against the sweep first.


### 8.15 Friday 2026-11-13, 06:10: bug audit, realistic timing, fixed panels, re-baseline started

- **Bug audit (four independent reviews of the backtest, the data builders, the alternative-data scripts and the live path).** The two findings that change results:
  - **Same-close look-ahead on fundamentals.** Sharadar's filing date is often an after-close earnings release. The backtest used the new numbers at that day's close, so it booked the next morning's price gap: +0.33% on average for the strongest minus weakest earnings surprises. Every close-fill result, the live model's included, is inflated.
  - **Market-cap look-ahead (fixed).** Sharadar's share counts are adjusted for later splits, so future winners looked bigger than they were. Market cap now comes from Sharadar's point-in-time figure, which matches the next filing within 25% for 97% of filings. This affects 175 results that used market-cap sizing. They are moved out of the leaderboard (sweep results_lookahead_mcap/), including the round 46/47 "four" leads of 1.415 and 1.502. The live account never used this sizing.
- **How much the look-ahead was worth (round 50, live model, ranks 201-1000, 2000-today).** Excess Sharpe over T-bills; SPY scores 0.513 on the same measure:

  | Timing | Excess Sharpe |
  |---|---|
  | Filing usable same close, close fills (old backtest) | 1.134 |
  | Fundamentals 1 day later | 1.092 |
  | 2 days later | 1.081 |
  | 5 days later | 1.058 |
  | 2 days later + next-open fills | 1.062 |
  | 2 days later + next-open fills + 20 bps costs | 0.918 |

  The look-ahead was worth about 0.06-0.07, mostly after 2011. The model stays well ahead of SPY. Costs matter more than timing: 20 bps instead of 10 costs 0.14. The weekly fill reconciliation will show the real figure.
- **Fundamentals panels rebuilt with three fixes.** Cells changed: 1-4% depending on the feature; rank correlation with the old panels 0.96-1.00.
  - A missing quarter is now a gap, not stitched over. About 2.4% of company-quarters were affected; for example Apple's July 2006 quarter is missing in Sharadar, and its year-over-year comparisons now skip it.
  - Filings older than 400 days now really expire. The backtest used to carry them forward forever.
  - Nine live tickers are no longer matched to an older, different company, e.g. Fox Corp to Fox Entertainment.
- **Re-baseline queued (round 51, 74 variants, 148 runs, ahead of everything else).** Every run uses realistic timing: fundamentals usable the next day and fills at the next open, which is how the live account trades. It covers:
  - the live model;
  - every round 46 rule alone and in pairs, and the "four" combination with its neighbours and costs;
  - the top 200 names included;
  - ranks up to 3,000.

  Old-timing jobs still in the queue are parked (sweep hold_oldtiming/). Nothing will be promoted until this baseline is in.
- **Free alternative data (round 49: 460 variants, 589 runs, all with realistic timing and their own controls).**
  - Downloaded: short interest, daily short volume, SEC 13F holdings, EDGAR filing events, 36 FRED macro series.
  - Still downloading: Benzinga news with full text (at 2021-05), FINRA dark-pool volume (at 2022-12).
  - 383 runs are queued behind round 51; the rest are added as their panels appear.
  - 13F holdings fix: some filers report value in dollars where the form asks for thousands, so a holding whose implied price is far from the median filer's is corrected.
- **Sharadar rate limit:** the 429 "account temporarily disabled" seen at 01:55 is on the Nasdaq Data Link endpoint only. The endpoint the daily job uses (api.sharadar.com) answered normally at 05:20.
- **Live-path issues found by the audit (not changed; waiting for a decision):**
  - every name is re-traded to its target daily, so the no-trade band never applies (51 orders on 11-12 where 20 were needed, 29 under $50);
  - orders are regular market orders filled at 09:30-09:34, not opening-auction orders;
  - there is no check that the data is current;
  - a Sharadar outage skips the day with no alert;
  - the scheduled task runs only while logged in;
  - the live fundamentals code has the same missing-quarter and never-expire bugs as the old panels.


### 8.16 Friday 2026-11-13, 09:20: live fixes, realistic-timing baseline, round 52

- **Live-account fixes (the user chose all three groups; commit 03f6c18).**
  - The no-trade band now works live: each day starts from the account's actual weights, and names inside the band are not traded. A dry run on 11-12 data sent 19 orders instead of 51.
  - Orders go to the opening auction, which is how the backtests now fill. Alpaca accepts auction orders only after 19:00 ET, so the scheduled task now starts at 17:30 CT and sends at 18:01 CT.
  - Safety checks: no trading on stale or half-updated price data; holidays exit quietly; a Sharadar outage falls back to cached data and logs an error; state and log files are saved safely; the fill-check script reads every order.
  - The live fundamentals code now has the same three data fixes as the backtest panels, and gives exactly the same values on 565 sampled names and 9 features.
  - One step is left for the user: the scheduled task still runs only while they are logged in.
- **Realistic-timing baseline (round 51, ranks 201-1000, 2000-today):**

  | Variant | Stitched | Excess | CAGR |
  |---|---|---|---|
  | Live model, old timing, old panels | 1.264 | 1.097 | - |
  | Same, fixed panels | 1.252 | 1.085 | 13.6% |
  | Live model, realistic timing | 1.188 | 1.021 | 12.9% |
  | Realistic timing, 15 bps costs | 1.118 | 0.952 | - |
  | Realistic timing, 20 bps costs | 1.048 | 0.882 | - |
  | Best so far: risk-parity sleeve + summer de-risking | 1.327 | 1.129 | 12.2% |

  The panel fixes cost 0.012 and realistic timing another 0.064. The rules that helped before still help under realistic timing, but by less.
  
  Not promoted: the best variant lowers CAGR from 12.9% to 12.2%, and the promote rule requires CAGR to rise. Round 51 is about half done.
- **Round 52 queued (1,121 runs):** every live-base variant from rounds 38-48, rerun with realistic timing on the fixed panels.
- **Fails-to-deliver data now goes back to 2004.** The older SEC files report only fails of 10,000 shares or more before September 2008, so that threshold is applied to every year.
- **Sweep fixes.**
  - The fixed panels hold every name, and a 1,000-name run that loaded them in full needed 7 GB and was killed. Runs now load only their own names and dates; the features are identical and memory use for those panels fell from 0.75 to 0.03 GB.
  - 14.7 GB of retired panels were moved to E:\SweepData\archive and 7.1 GB of stale caches deleted. C: has 40.6 GB free.


### 8.17 Saturday 2026-11-14, 11:15: new leader, the four-rule model on ranks 201-2500 (rounds 51, 53, 54)

- **Switched the paper account** (config only; Monday 11-16's 17:30 job is the first to trade it). Same ranker (sue_fcfy_q6) on liquidity ranks 201-2500 instead of 201-1000, plus four rules:
  - **Altman Z screen:** names below 1.81 (the distress zone) leave the ranking; a held one is sold.
  - **Fresh entry:** a name not held may be bought only within 21 trading days of its last filing.
  - **Market-cap sizing:** weight grows with the square root of the point-in-time market cap, so the smallest names stay small.
  - **Risk-parity sleeve:** IEF / GLD weighted by inverse 63-day volatility instead of equally (today about 80% / 20%).
- **Results (realistic timing: next-open fills, filings usable the next day; complete panels):**

  | Model | Stitched | Excess | 2000-10 | 2010+ | CAGR | Max DD | Worst year |
  |---|---|---|---|---|---|---|---|
  | Old live, ranks 201-1000 | 1.188 | 1.021 | 1.387 | 1.063 | 12.9% | -18.3% | -8.7% |
  | **New, ranks 201-2500** | **1.357** | **1.189** | **1.760** | **1.117** | **14.8%** | **-21.7%** | **-10.7%** |
  | SPY controls (best: gates + sleeve) | 0.885 | 0.713 | - | - | 9.0% | -21.1% | - |

- **Trading costs measured by liquidity rank.** Small names cost more to trade than the flat 10 bps the backtests charge, so the spread was estimated from Norgate daily high / low / close (Abdi-Ranaldo, 2000-2026, price >= $5). The estimator overstates every name's level, so only the extra cost over ranks 201-1000 was used:

  | Ranks | Extra half-spread 2000-04 | 2005-09 | 2010-14 | 2015-19 | 2020-26 |
  |---|---|---|---|---|---|
  | 1001-1500 | +5 bps | +1 | +1 | +2 | +3 |
  | 1501-2000 | +11 | +5 | +4 | +5 | +6 |
  | 2001-2500 | +16 | +10 | +6 | +7 | +7 |
  | 2501-3000 | +19 | +16 | +10 | +10 | +8 |

  Every trade was then charged 10 bps plus its rank's extra cost for that era (new sweep option `cost_rank`):

  | Model under the measured cost | Stitched | 2000-10 | Max DD |
  |---|---|---|---|
  | Old live, ranks 201-1000 | 1.183 | 1.382 | -18.5% |
  | Ranks 201-2250 / 2500 / 2750 / 3000 | 1.320 / **1.333** / 1.325 / 1.334 | 1.74 / 1.73 / 1.77 / 1.82 | -21.5 / -21.7 / -23.5 / -23.6% |
  | Ranks 201-2500 at double the extra cost | 1.309 (old live: 1.177) | 1.700 | -21.8% |
  | Ranks 201-2500 at 13 bps + extra (our fills) | 1.299 (old live: 1.141) | 1.698 | -21.9% |

  Ranks 201-2500 ties 201-3000 with a smaller drawdown and a better 2010+ Sharpe (1.097 vs 1.043), and keeps a clear margin from the -25% limit under every cost.
- **Real fills so far (323, 11-09 to 11-13, ranks 201-1000):** median 0 bps vs the open, +12.8 bps notional-weighted; the backtest assumes 10.
- **Checks before switching.**
  - All four rules were new to the live code. Each was ported (tests/test_wide_port.py) and gives the same result as the sweep code on real data: Altman Z on 352 companies / 8,939 filings, market cap on 300 names (max difference 2e-7), sizing and screen in 300 random cases each, the fresh-entry mask exactly. The sleeve prices differ only in the last week, where the sweep's cached ETF prices stop on 11-06.
  - Exact replay: the 2000-2010 half matches to zero; the 2005-2026 half differs by at most 0.09% on a day (Sharpe 1.1171 vs 1.1173), from a data rebuild on 11-14. Stocks plus sleeve never exceed 98.1% of the account.
  - 118 tests pass. Dry run on 11-13 data: 68 orders, 32% stocks / 53% IEF / 13% GLD under today's low exposure; peak memory 6.3 GB (the old model's job used 5-6 GB).
  - The live fundamentals now fetch three more Sharadar fields (total liabilities, working capital, retained earnings); the first run refetched every row once.
- **Not changed:** `scripts/run_backtest.py` does not yet wire the market-cap and fresh-entry rules, so it cannot run this config.
- **Sweep fixes.** 36 macro-gate runs had failed after the 11-13 memory fix stripped the FRED columns from their panel; fixed and requeued. The sweep's pause window around the daily job moved to 17:24-17:35 to match the new start time.
