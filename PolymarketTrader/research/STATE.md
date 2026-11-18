# Research loop: state

The user asked (2026-11-18, before going to bed) for strategy research to keep running: every strategy family
that can be tested, and combinations of families, with settings varied. This file is what each hourly check-in
reads first. Keep it short and current. Findings go in the report; this is the control sheet.

**Report:** `reports/2026-11-18_strategy_research.md` (create on first results; add a dated section per check-in).

## Decisions already made

- **Venue: Kalshi.** Measured live on 2026-11-18 with the same filters: 570 markets in 273 events pass on Kalshi
  against 96 on Polymarket US; 86 against 6 or 7 are deep enough to trade. Kalshi's taker fee is lower (0.07
  against 0.095) and it is open in every state. The user lives in Illinois and said to use whichever is better.
- **Paper only.** No account, no keys, no orders. Live trading stays a stub (`docs/GO_LIVE.md`).
- **Language-model forecasts cannot be backtested** (the model has read about the past). They are tested forward
  only, by the paper bot. Everything backtested here is mechanical: rules on prices, time, category and structure.

## Rules for judging a result (do not relax these)

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

| Job | Command (from `PolymarketTrader/`) | Log |
|---|---|---|
| Kalshi history download | `setsid nohup python3 -u research/kalshi_download.py --interval 0.4 --min-volume 200 --first-pass 2500 >> data/kalshi_download.log 2>&1 < /dev/null &` | `data/kalshi_download.log` |

Check with `pgrep -af kalshi_download` and `tail -3 data/kalshi_download.log`. It is resumable: if it died, run
the same command again. If `data/` is gone (new container), run it again from scratch; listing takes about 1.5
hours and bars arrive at roughly 8,000 markets an hour.

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

1. Rerun the sweep as data lands: `python3 research/run_sweep.py --round r02_<what>`; first when Economics has
   its 4,000 markets, then per category, then all categories together. Add a report section per round (data
   seen, counts of pass / lead / loses, the tables that matter, what it means). Follow every lead with a round
   that tests it where it was not found (other categories, the other half of the sample, tighter and looser
   settings) before calling it anything.
2. For rules that pass: run `research/portfolio.py` on them (stake 0.5%, 1%, 2% of equity; event cap 3%;
   exposure cap 50%) and report return per year, drawdown and time in the market.
3. Finish the bot's live Kalshi run (Progress, 17:26), fix what live data shows, then run a paper cycle every
   few hours to build the forward record of Claude forecasts (family 17).
4. Families still to code: the NO side of ladder inversions; sums of mutually exclusive events (needs the
   event's `mutually_exclusive` flag: download `/historical/events` or `/events/{ticker}`); hourly bars for the
   last two days before close; sports and crypto samples (`--categories Sports` on the downloader, last).
5. After the non-sports first pass finishes, the downloader continues on its own with a second pass (all
   remaining markets of 200+ contracts) and then the recently settled markets. Leave it running.
