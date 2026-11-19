# Research loop: state

The user asked (2026-11-18, before going to bed) for strategy research to keep running: every strategy family
that can be tested, and combinations of families, with settings varied. This file is what each hourly check-in
reads first. Keep it short and current. Findings go in the report; this is the control sheet.

**Report:** `reports/2026-11-18_strategy_research.md` (create on first results; add a dated section per check-in).

## Decisions already made

- **Times for the user: US Central, 12-hour with am/pm** (asked 2026-11-18, 4:34 pm CST). Applies to every
  message and to new report text; logs stay in UTC. `TZ=America/Chicago date "+%-I:%M %p %Z"`.

- **Venue: Kalshi.** Measured live on 2026-11-18 with the same filters: 570 markets in 273 events pass on Kalshi
  against 96 on Polymarket US; 86 against 6 or 7 are deep enough to trade. Kalshi's taker fee is lower (0.07
  against 0.095) and it is open in every state. The user lives in Illinois and said to use whichever is better.
- **Paper only.** No account, no keys, no orders. Live trading stays a stub (`docs/GO_LIVE.md`).
- **Language-model forecasts cannot be backtested** (the model has read about the past). They are tested forward
  only, by the paper bot. Everything backtested here is mechanical: rules on prices, time, category and structure.

## Rules for judging a result (do not relax these)

0. **Two samples are valid, nothing else.** `--sample random` (default): every market that ever traded, in the
   download's fixed shuffle; mostly tiny markets with wide quotes. `--sample liquid`: the census of busy markets,
   where a market is seen only from the bar at which it had traded the census level (`cumvol`), so the
   biggest-first download carries no hindsight. Never pass `sample="all"` to judge a rule, never filter on
   `tot_vol`: use `cumvol` or `dvol7`, which are known at the bar. Rounds r01 to r04 (report 3.1 to 3.5) used
   neither and are superseded.
0b. **Days to close come from the schedule.** Kalshi rewrites `close_time` when a market closes early, so
   `dte` uses the expected expiration for markets that can close early (`markets.early`, `markets.exp_ts`;
   `panel.describe` prints "SCHEDULE MISSING" if the back-fill has not reached a category). Holding times in
   `analyze_rule.py` and `portfolio.py` use the real close.
0c. **Lopsided bets get the tail test, not a t-statistic.** For anything bought above about 85c run
   `research/analyze_rule.py`: losing events against the break-even loss rate with an exact upper bound.
1. **Costs in.** Taker entries pay the ask plus Kalshi's fee, 0.07 × p × (1 − p) per contract (some series carry
   a different multiplier: `series.fee_multiplier`). Maker entries are counted only when a later bar shows the
   price trading through the order, and are reported separately from taker results.
2. **Out of sample.** Choose settings on markets that closed before 2026-04-01; report the result on markets
   closing from that date. The date was fixed on 2026-11-18 from the calendar alone, before any result was seen:
   Kalshi's history is concentrated in 2026 (for Economics, 43% of events closed before April 2026; for Weather,
   58%). A strategy that only works in-sample is not a result. Do not move the date.
3. **Errors clustered by event.** Markets of one event move together. t-statistics use one observation per event
   (or event-day), never one per market.
4. **Multiple testing.** With N variants tried in a family, the best is expected to look good by luck. Require
   out-of-sample t above 3 for a first claim, and say how many variants were tried.
5. **Capacity.** Report the dollars actually available at the quoted price where the data allows; a rule that
   earns 5% on $3 of depth is not a strategy.
6. **Nothing reaches the paper bot's config** without the evidence written into the report first, and nothing
   ever loosens `safety` or `sizing` limits.

## Background jobs

Start whatever is not running, at any time: **`bash research/start_jobs.sh`** (from `PolymarketTrader/`). It
starts the Kalshi history download (resumable; log `data/kalshi_download.log`) and the paper loop
(`scripts/paper_loop.py`, one cycle every 3 h by the ledger's clock; log `data/run_cycle.log`). After each cycle
the loop also runs `scripts/shadow_longshot.py`: the forward observation log of the longshot rule (no orders; its
own file `data/shadow.db`; `python3 scripts/shadow_longshot.py --report` for the summary to quote in the report).

Download order per category: list its settled markets (with scheduled end dates), back-fill schedules for older
listings, 2,500 random markets' bars, then the census (every market with 5,000+ lifetime contracts, biggest
first, at most 8,000). `research/panel.py` works out by itself how far down the census is complete.

**THE MACHINE SLEEPS WHEN THE SESSION IS IDLE** (found 20:21: `uptime` showed 3 minutes; the download's last write
was 2 minutes after the previous turn ended). Detached jobs do not keep it awake. A task tracked by the session
does. So EVERY check-in, after `start_jobs.sh`, must leave this running as a Bash call with
`run_in_background: true` and `timeout: 7200000`:

```
cd /home/user/StockTrader/PolymarketTrader && n=0; while pgrep -f "research/kalshi_download.py" > /dev/null && [ $n -lt 115 ]; do sleep 60; n=$((n+1)); done; date -u +%T; uptime; tail -1 data/kalshi_download.log | cut -c1-160
```

It ends after about two hours (or when the download stops) and its completion notice is the cue to restart both.
The "PolymarketTrader job watchdog" check-in (minute 21) should do the same: run the script, then leave the
keep-awake task running.

The paper loop is the forward test of Claude's forecasts (family 17). Its ledger is `data/pmt.db` (not committed);
`python3 scripts/export_forecasts.py` writes the durable copy, `reports/forward_log.csv`, which IS committed: run it
and commit at every check-in. `data/cloud_config.yaml` is config.yaml with: no quiet window, 2 runs, medium effort,
4 markets, 40 books, 2 s pacing. If `data/` is gone (new container): recreate that file, run the script, and
expect the listing to take about 1.5 hours per category before bars arrive (about 2,500 markets an hour when
Kalshi throttles, 9,000 when it does not). The first cycle after a loss of `data/` starts a NEW paper account:
say so in the report, and keep `reports/forward_log.csv` (append, do not overwrite the old rows).

The download writes `data/kalshi_hist.db` (tables `series`, `markets`, `candles`). It is not committed: Kalshi's
terms do not allow redistributing its data. Commit code, aggregated results and reports only.

## Progress

- 2026-11-18 16:59 UTC: download started; restarted 17:08 in priority order (Economics, Politics, Companies,
  Commodities, Science and Technology, Elections, Health, World, Financials, Mentions, Entertainment, Crypto,
  Social, Climate and Weather). Each category: list its settled markets, then daily bars for its 6,000 biggest.
- 17:10: Kalshi adapter (`src/kalshi.py`) built, tested offline against real payloads, made the default venue.
  NOT yet run live end to end: do `python scripts/run_cycle.py --scan` first (pause the download while it runs,
  the two share Kalshi's rate limit: `pkill -STOP -f kalshi_download`, then `pkill -CONT -f kalshi_download`).
- 17:12: backtest engine committed (`research/panel.py`, `backtest.py`, `families.py`, `run_sweep.py`). Checked
  on a made-up exchange: with fair prices no taker rule passes; a planted bias is found on the right side.

- 17:26: first live Kalshi scan ran past 8 minutes under rate limiting. The adapter now keeps the listing on disk
  (`data/kalshi_listing.json`, refreshed at most every 20 h) and resumes a cut-off scan. A slow background scan
  is filling it: check `python3 -c "import json;s=json.load(open('data/kalshi_listing.json'));print(bool(s.get('finished')),len(s['markets']))"`.
  When it says True, run `python3 scripts/run_cycle.py --config data/cloud_config.yaml` (cloud config: no quiet
  window, 2 runs, medium effort, 4 markets, 2 s pacing; recreate it from config.yaml if data/ was lost).
- 17:45: round `r01_economics_prelim` on the first 1,476 Economics markets: all rules thin (411 events). Report
  section 3.1. The download reaches about 9,000 markets an hour when Kalshi is not throttling.
- Sample split fixed at 2026-04-01 (see rule 2 above). Account replay simulator added (`research/portfolio.py`).

- 17:55 (check-in 1): round `r02_economics_2760`, report 3.2. 0 pass, 19 leads (all "buy NO", not significant in
  sample, concentrated in "above X" markets of 2025-26), 18 reliably losing (taker YES on favourites; taker NO
  against longshots). Engine gained fixed-horizon snapshots (family 1b) and an event-weighted statistic; `pass`
  now needs both weightings. Both background jobs alive (download at Economics bars 3,000 of 4,000; bot listing
  partial).
- New backlog items from r02: (a) test "buy NO at 20-80c" and "favourites lose" in every other category as it
  lands; (b) split by strike_type greater / less / between wherever "less" exists; (c) year-by-year table for
  any lead; (d) does the favourite loss shrink with a resting entry and near the close?

- 18:00: round `r03_economics_4000` (Economics first pass complete: 3,215 markets, 845 events), report 3.3.
  0 pass, 9 leads, 15 lose. Solid: taker NO against 5-20c longshots loses; taker YES on favourites loses. Leads to
  re-test on other categories: buying thin 5-20c longshots; NO on markets listed 2-7 days ago. Download has
  moved on to Politics (2,526 series to list, then bars).

- 18:52 (check-in 2): slow listing scan stopped (it was starving the download); the bot's listing was built from
  the full snapshot captured at 11:33 (4,489 markets, valid 20 h; after that the adapter rescans by itself, slowly).
  FIRST LIVE KALSHI CYCLE DONE: 4 forecasts (3 low confidence, not traded), 1 paper order: resting NO $20 @ 0.65
  on KXGOVTSHUTDOWN-26DEC12 (Claude 0.205, market 0.345). Paper loop started, every 3 h. Commodities removed from
  the bot's categories. Download restarted with `--first-pass 2500` (Politics in progress).

- 19:55 (check-in 3): both jobs were dead (worker restart about 19:10); restarted with `research/start_jobs.sh`;
  watchdog trigger added. No new round (Politics has only 560 markets with bars). Year-by-year breakdown of the
  two Economics leads: both dropped (report 3.4). Rule for the future: any lead gets a year-by-year and
  concentration table before another round is spent on it.

- 20:55 (check-in 4): keep-awake confirmed (machine up 32 min, Politics 680 -> 1,840 markets). Round r04 (Politics;
  Economics + Politics): 1 pass, 49 leads, 50 lose, the same "dear side loses" pattern in both categories.
  THEN FOUND THE SAMPLING FLAW (report 3.5). Download switched to a fixed random order (`rnd` = crc32 of the
  ticker), minimum volume 1, first pass 2,500 random markets per category, Economics first. Panel uses the
  random sample only. Next round must be on the random sample and must say whether the r02-r04 pattern survives.

- 4:40 pm CST (check-in 5, 22:40 UTC): r05/r06 superseded the same hour by **r07** (after the schedule fix, with
  families 16 to 26). Random Economics and Politics: 0 pass; the r02-r04 "dear side loses" pattern is gone
  (report 3.6). Busy markets, Economics + Politics at 45,000 contracts: 22 pass, 49 leads, all "buy NO where
  YES is cheap" (report 3.7). The 5-cent rule taken apart (3.8): tail test passes both halves; small in dollars;
  all losses in 2025-26. Forward observation log started (3.9). Paper bot config NOT changed: the rule needs
  prices above `sizing.max_price`; left as the user's decision (second paper account).
  Download: Economics census down to 5,000 contracts in progress, then Politics random pass and census, then
  Companies onward.

- 4:53 pm CST (check-in 6): nothing new had landed since 4:40 pm. Calibration curve added (report 3.10). Volume
  gradient seen in family 23 (NO against YES at 0-5c, taker, in / out of sample): under 1,000 contracts so far
  +0.2% / -3.2%; 1,000-10,000: -0.4% / -0.6%; 10,000-100,000: +0.5% / +0.8% (random sample, thin). So the edge
  starts somewhere above 10,000 contracts: test it properly when the Economics census reaches 5,000
  (`--sample liquid` with no `--min-cumvol`), and write the answer into the report.

- 5:48 pm CST (check-in 7): CONTAINER RESTARTED about 5:45 pm; `data/` survived; jobs and keep-awake restarted.
  Economics census complete to 5,000 contracts. Round r08 (report 3.11): 5-cent rule holds at that level (tail
  test passes both halves; 2024 a losing year); the wider NO edge (5-35c) fades to zero at this level. Politics
  random pass resumed, then its census, then Companies.

- 5:53 pm CST (check-in 8): jobs alive, nothing new landed. Listed the rule's losing bets (report 3.11): macro
  data surprises, three of nine from January 2024 releases; Politics losses are "X happened before the date".
  Idea for the backlog: cap the rule's exposure per release month / per underlying statistic, and test whether
  skipping "data release above X" thresholds within N standard moves helps (needs the release history; later).

- 6:52 pm CST (check-in 9): second container restart about 6:40 pm, data intact. Round r09 (report 3.12):
  random Politics complete, 1 pass of 2,780 (chance). Busy at 15,000 contracts, both categories: 60 pass, all
  buy-NO. BUT the 5-cent rule as a TAKER fails the tail test on Politics alone (2025: -1.6% per bet); resting
  passes. Politics census still descending from 14,452 to 5,000: re-run `--sample liquid --categories Politics`
  when `research/panel.py`-level check shows it complete, then Companies.

- 8:07 pm CST (check-in 10): Politics census complete to 5,000. Round r10 (report 3.13): at 5,150+ contracts in
  both categories, 26 pass / 117 leads, all buy-NO, BUT paying the ask for NO is worth about zero in every band;
  the 5-cent TAKER rule fails in Politics (+0.14% per bet) and is carried by Economics; the RESTING version
  passes pooled (fill is modelled). Closing-window check: nothing special in the last 1-3 days; hourly bars
  dropped. Status section of the report rewritten. Download now on Companies.
  BUILT 8:10 pm: resting-fill tracking in `scripts/shadow_longshot.py` from Kalshi's public trades (queue-aware;
  3-day window). `--report` prints the fill rate and, once settled, the return of the filled ones: quote it in
  the report at each check-in once more than about 20 are decided.

- 8:55 pm CST (check-in 11): Companies too small (79 events). Commodities moved behind the bot's categories;
  download now on Science and Technology. Report 3.14: the WIDE resting rules (NO against YES up to 35-50c) have
  positive means per bet but LOSE in the account replay (gains sit in huge multi-outcome events; event-weighted
  t negative). Calibration gap per event: solid under 5c, gone above 10c out of sample: the "corrected starting
  price" idea for the bot is withdrawn. Lesson for judging: always run `analyze_rule.py` (replay) and read
  `oos_evt` before calling anything usable.

- 9:55 pm CST (check-in 12): downloader bug fixed (a ticker with "%" was retried for ever and held the Science
  and Technology random sample at 811 markets); Science and Technology still downloading (about 2,165 of 3,906
  with bars). New family 27, `research/event_baskets.py`: NO on every outcome of an event whose YES bids add up
  to more than 1. On the "no numeric strike" proxy it LOSES (most such events are not exclusive: "by June" and
  "by December"). Fetching Kalshi's own `mutually_exclusive` flag for the candidate events (file `data/kalshi_events.db`) to
  test the exclusive ones alone: result goes in the report as 3.15.

- 10:06 pm CST: family 27 done (report 3.15). With Kalshi's flag (154 of 405 candidate events are exclusive):
  bids of an exclusive event's outcomes add up to 1.00-1.02, basket locked at about -0.9% after fees; reached
  1.05 once in five years. No arbitrage. Flags are in `data/kalshi_events.db` (not committed).

- 10:53 pm CST (check-in 13): Science and Technology complete. Round r11 (report 3.16): random 0 pass; busy
  0 pass / 11 leads (all resting NO). 5-cent rule: taker fails there too (+0.08%); pooled over three categories
  the RESTING version passes both halves (+1.98% per bet, 1,270 events), the TAKER fails both. Fixed a crash on
  a missing title. Download is listing Elections (2,601 series), then Health, World.

- 11:56 pm CST (check-in 14): Elections still listing. FOUND AND FIXED A FLAW IN `portfolio.entries`:
  same-day bets were ordered by return, losers first (pessimistic look-ahead). All replay figures of report 3.8
  to 3.16 were too low; corrected table in 3.17; means, t and tail tests were never affected. New tool
  `research/resting_variants.py`: 5 depths x 3 windows for the resting NO bid, all 15 pass the tail test in both
  halves (report 3.17): no setting to tune.

- 12:54 am CST Nov 19 (check-in 15): Elections random pass complete, census at 22,000 contracts and descending.
  Round r12 (report 3.18): Elections shows NO longshot effect of its own (0 pass; 5-cent rule +0.07% taker, +0.91%
  resting, few bets). Four categories pooled at 23,000+: both versions pass the tail test in both halves.
  Next: Elections to 5,000, then Health and World (small), then pooled five/six-category rounds at 5,150.

- 1:57 am CST Nov 19 (check-in 16): ALL SEVEN BOT CATEGORIES DOWNLOADED. Round r13 (report 3.19), pooled busy
  sample 17,522 markets / 5,316 events: 17 pass (16 buy NO against cheap YES). 5-cent rule pooled: RESTING passes
  both halves (+1.85% per bet; replay +3.6% / +14.8% a year); TAKER fails (+0.43%). The effect lives in
  SINGLE-MARKET events (taker 5 losses in 696) and Economics; absent in Elections and inside multi-outcome
  events. `ev_total` now counts the markets the exchange listed (was: markets in the sample).
  Download has moved to Commodities (random 2,500 then census, capped at 8,000), then Financials etc.
  NEXT IDEAS: (a) 5-cent rule restricted to single-market events with <= 30d and by category; (b) the same
  breakdown for YES 5-20c; (c) forward log: add single-market flag to `scripts/shadow_longshot.py`.

- 2:58 am CST Nov 19 (check-in 17): family 28 (stand-alone questions), report 3.20: strong in sample (t 4-16,
  280-600 events), positive with no loss since April 2026, but every rule is THIN out of sample (10-87 events):
  not a pass, and the split / 100-event bar stay where they are. `scripts/shadow_longshot.py` now records the
  event's size (`ev_markets`). Commodities census in progress (about 2,900 of 8,000).

## How to run a round

```
cd PolymarketTrader
python3 research/panel.py                               # what has been downloaded so far
python3 research/run_sweep.py --round r01               # every rule of every family -> research/results/r01.csv
```

A round takes a few minutes. Name rounds r01, r02, ... and say in the report which data each one saw (the
panel's first line: markets, events, dates), because the download keeps growing.

## Backlog of strategy families (mechanical, backtestable)

Status: `todo`, `running`, `done` (with the report section), or `dropped` (with the reason).

1. todo: Price-level calibration (favourite-longshot): return to buying YES and to buying NO by price bucket,
   by category, by days to close.
2. todo: Favourites near expiry ("bonds"): 85-99 cents with 1 to 14 days left.
3. todo: Always-No, by category and by event size (many-outcome events).
4. todo: Momentum and reversal: 1, 3, 7-day price change, follow or fade.
5. todo: Deadline decay: "by date" markets drifting to No; buy No early.
6. todo: Ladder consistency: thresholds of one event must be ordered (P(above 3.6) >= P(above 3.7)); trade
   violations. Mutually exclusive sets summing above or below 1.
7. todo: Volume and attention: thin against busy markets; first days after listing; volume spikes.
8. todo: Spread and maker economics: what a resting bid earns by price level and category, with the
   trade-through fill rule.
9. todo: Closing-window effects: last 24 to 72 hours.
10. todo: Opening-price effects: first quoted prices against later ones.
11. todo: Series-specific persistence: does a series that was biased last year stay biased this year?
12. todo: Calendar effects: day of week, month, release-day proximity for economic series.
13. todo: Extremes: prices that jump more than X in a day, continuation or reversal.
14. todo: Combinations: the survivors of 1-13 crossed pairwise (for example favourites x near expiry x maker
    entry x category), then the best triples.
15. todo: Portfolio rules on the survivors: Kelly fraction, per-event caps, capital lock-up, drawdown.
16. todo: Sports and crypto as separate samples (download them after the non-sports set is analysed).

Forward-only (cannot be backtested):

17. todo: Claude forecasts on Kalshi through the paper bot (needs the Kalshi venue adapter, `src/kalshi.py`).
18. todo: Claude as a filter on a mechanical rule (trade the rule only where Claude does not object).

## Next actions

1. Each check-in: `python3 research/panel.py` (what landed), then for every category with a finished pass run
   both samples: `python3 research/run_sweep.py --round rNN_random_<cat> --categories <Cat>` and
   `... --round rNN_liquid_<cat> --categories <Cat> --sample liquid` (default level = as far down as the census is
   complete; use `--min-cumvol 45000` when comparing with report 3.7). `python3 research/round_tables.py <round>`
   prints the tables for the report.
2. **Re-test the 5-cent rule on every new category and at the lower census level** (Economics is being extended
   to 5,000 contracts): `python3 research/analyze_rule.py --sample liquid --categories <Cat> --rule "NO at mid <= 5c,
   <= 30d, spread <= 5c" --side no --entry tk` (and `mk`). A category where it fails is a result too: write it.
2b. **Calibration curve** (report 3.10, 3.14): `python3 research/calibration_curve.py --sample liquid --categories
   <Cat>`; read the per-event columns. Re-measure on each new category. The bot-prior correction is withdrawn.
3. Leads to follow on the busy sample: NO where YES is 5 to 35c, resting (+6% / +6%, t 2.1 out of sample, thin);
   NO at 3 to 10c after a fall of 3c+ (momentum cross). They need more events: wait for more categories.
4. Forward: `tail -20 data/run_cycle.log`; `python3 scripts/shadow_longshot.py --report`; commit
   `reports/forward_log.csv`; one line each in the report.
5. Still to code: sums over mutually exclusive events with Kalshi's own flag (needs `/events`); hourly bars for
   the last two days; exits before settlement (sell the NO at 99c instead of waiting); a combined-portfolio
   replay of several passing rules; sports and crypto samples last.
6. Open for the user: trade the 5-cent rule in a second paper account? Which Claude model for the forecaster?
