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
