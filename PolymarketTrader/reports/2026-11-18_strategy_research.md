# Strategy research on Kalshi history
*Started Wednesday 2026-11-18. A running report: newest status first, then method, then one dated section per
round. Nothing here has been traded, on paper or otherwise.*

## Status

- **No strategy has passed, and the results so far are under a cloud of my own making.** Rounds 3.1 to 3.5 used
  markets downloaded biggest-first. "Biggest" means lifetime volume, which is only known afterwards and is larger
  for markets where something surprising happened. That can manufacture exactly the pattern those rounds found
  (favourites losing, longshots paying). Section 3.5 explains; the download now draws markets at random and the
  backtests use only the random sample. Treat 3.2 to 3.5 as provisional until the random sample confirms or
  overturns them.
- **Provisional pattern, same in Economics and Politics:** paying the ask for the high-priced side lost on both
  sides of the sample split, and the low-priced side looked cheap. If it survives random sampling it is the main
  finding; if it does not, it was the sampling.
- **Forward test of Claude's forecasts has begun** on Kalshi, paper only: 4 forecasts, 1 resting paper order
  (`reports/forward_log.csv`).
- **Data is still downloading.** Kalshi's public API throttles hard, and this session's machine sleeps when
  idle, which cost about an hour and a half before I found it (section 3.5).

## 1. Method

**Data.** Settled Kalshi markets from the exchange's public archive (2021 to September 2026) plus markets settled
since, with daily bars of bid, ask and traded price. Since 20:53 UTC on 2026-11-18 the download draws markets in a fixed random order within each category and
takes any market that ever traded; backtests use only that random sample. (Before that it took the biggest
markets first, with a 200-contract minimum: see section 3.5 for why that was a mistake.) Liquidity conditions in
a rule must use volume as it stood at the time of the bar, never lifetime volume.

**One observation per market per day.** A rule may look only at what was known at the end of a daily bar: the
quote, the days left, the market's age, recent volume and price changes, and the other markets of the same event.

**Entries.** One per market, at the first bar on which the rule's condition holds.
- *Taker:* buy at the next bar's opening ask (or one minus the bid, for NO) and pay Kalshi's fee,
  0.07 × price × (1 − price) per contract.
- *Resting:* leave a bid at the bar's closing bid for up to three bars. It counts only if the ask later came down
  to it or a trade printed below it. Series that charge resting orders pay that fee too.

**Exit.** Hold to settlement. Returns are per dollar staked, after fees.

**Judging a rule.** Fixed before any result was seen:
- *Split.* In sample is markets closing before 2026-04-01; out of sample is from that date. Kalshi's history is
  concentrated in 2026, so this puts roughly half the events on each side.
- *Sample size is events, not markets.* The markets of one event rise and fall together, so standard errors are
  clustered by event, and a rule needs 100 events on each side to be judged at all.
- *Pass:* positive on both sides, in-sample t of 2 or more, out-of-sample t of 3 or more. With about 4,000 rules
  in a round, pure chance produces about one such "pass" in four rounds; anything that passes is then re-tested
  on categories and periods it was not found on before it is believed.
- *Lead:* positive on both sides with out-of-sample t of 2 or more. Worth a follow-up round, not a conclusion.

**Checked against a made-up exchange.** With fair prices, no taker rule passes and the average rule loses about
the spread and the fee. With cheap contracts deliberately quoted 6 cents too high, selling them passes and buying
them loses. So the engine neither invents edges nor misses a planted one.

## 2. Families

| # | Family | What it asks |
|---|---|---|
| 1 | Price-level calibration | Is a contract at this price worth its price? By price band, days left, category |
| 2 | Favourites near expiry | Do near-certain contracts close to settlement pay more than their risk? |
| 3 | Always No | Does betting against everything pay, by event size and by whether the market is the event's favourite? |
| 4, 13 | Momentum, reversal, jumps | After a move of 3 to 20 cents in 1 to 7 days: follow it or fade it? |
| 5 | Deadline wording | Do "before" and "by" markets drift to No? |
| 6 | Threshold ladders | Are "above X" markets of one event priced in order? Lock-in pair trades |
| 7, 10 | Volume and age | Thin against busy markets; newly listed against old |
| 8 | Spread | Does a wide quote pay the side that rests in it? |
| 11 | Series persistence | Does a series that paid one side in the first half still pay it in the second? |
| 12 | Calendar | Day of week, month |
| 14 | Combinations | Price × days × category, × volume, × favourite, × momentum |
| 15 | Account replay | A rule's bets replayed through an account: lock-up, drawdown, return per year |
| 17, 18 | Claude forecasts | Forward only, through the paper bot |

## 3. Rounds

### 3.1 Round r01, Economics only, preliminary (17:45 UTC)

Data: 1,476 Economics markets in 411 events, 137,928 daily bars, closing 2022-01 to 2026-09; 484 markets out of
sample. These are the largest Economics markets only.

Result: **every one of 1,673 rules is "thin"**. No rule has 100 events on both sides; the out-of-sample half has
at most 85.

One pattern is worth writing down so it can be checked, not believed: in the out-of-sample months, contracts
priced 65 to 95 cents paid out far less often than their price (80 to 90 cents: 65% of 156 markets in 65 events).
I traced the losing bets to the raw bars. They are real: mostly weekly and monthly gas-price markets and CPI
markets in mid-2026, where prices swung from the 90s to single digits within days. It is 65 events concentrated
in two series and one volatile stretch. If favourites in economic-data markets are really overpriced, it will
show up again in the full Economics sample and in other categories.

### 3.2 Round r02, Economics, 2,537 markets (17:55 UTC)

Data: 2,537 Economics markets in 655 events, 208,946 daily bars, closing 2021-08 to 2026-09; 935 markets out of
sample. Two things were added to the engine first: a fixed-horizon snapshot (family 1b: the price a set number of
days before close, whatever path it took), and an event-weighted statistic that counts a 20-rung ladder once.

Result: 2,017 rules. **0 pass, 19 leads, 18 reliably lose**, 344 no, 1,636 still thin.

**What reliably loses** (negative on both sides of the split, both weightings):

| Rule (taker entries) | In sample | t | Out of sample | t | Events in / out |
|---|---|---|---|---|---|
| YES at 50c or more, 60 days before close | −13.6% | −4.7 | −23.8% | −4.8 | 327 / 110 |
| YES at 50c or more, 30 days before close | −9.3% | −3.3 | −20.3% | −4.4 | 335 / 115 |
| YES at 50c or more, 7 days before close | −9.7% | −3.6 | −18.1% | −3.7 | 324 / 115 |
| YES at 80 to 90c, first time there | −8.7% | −3.5 | −15.7% | −3.6 | 305 / 108 |
| YES at 80c or more, 30 days or less to go, tight spread | −4.1% | −2.1 | −10.4% | −3.4 | 297 / 109 |
| NO against a 5 to 10c longshot | −4.3% | −2.4 | −9.2% | −4.5 | 312 / 123 |
| NO against a 5 to 20c longshot quoted 6 to 15c wide | −5.9% | −3.2 | −12.8% | −4.5 | 283 / 112 |

Both ends of the price range are overconfident in this category: favourites win less often than their price, and
longshots come in more often than theirs. Fees and spread explain only 2 to 4 points of these losses. For the
paper bot this matters directly: the README's "lean to favourites" came from studies of other venues and is
wrong for Kalshi Economics on this evidence. Nothing in the bot's config depended on it (it trades 15 to 85
cents on Claude's disagreement with the price), so nothing changes yet.

**The leads all point one way: buy NO.** For example NO at 20 to 80 cents taken 30 days before close: +2.7% in
sample (t 0.5), +22.9% out of sample (t 2.3). None is significant in sample. Breaking the 7-day snapshot down:

- by strike type: the effect is in "above X" markets (588 of 723 bets); there are almost no "below X" markets
  to compare with, so a bias toward YES cannot be told apart from numbers simply coming in low;
- by series: weekly gas prices are a quarter of the bets and return +47%; payrolls return −7%;
- by year: NO lost in 2023 (−16%) and 2024 (−13%) and won in 2022, 2025 and 2026.

So this is a lead with a plausible boring explanation (gas prices and inflation prints came in below what markets
expected through 2025 and 2026). It gets tested where that explanation cannot apply: other categories, and
"below X" markets when enough exist.

**Momentum:** fading a rise (NO after +3 to +5 cents in a day) and following a fall both show up as leads out of
sample and nothing in sample. They are the same NO tilt wearing a different name, not evidence about momentum.

**Still thin:** every price × days cell, the ladders (10 rules), persistence (7), and all combinations.

### 3.3 Round r03, Economics first pass complete, 3,215 markets (18:00 UTC)

Data: 3,215 Economics markets in 845 events (the 4,000 biggest, less those never quoted), 243,542 daily bars;
1,201 markets out of sample. Same 2,018 rules.

Result: **0 pass, 9 leads (down from 19), 15 reliably lose.** Adding 190 events removed half the leads, which is
what leads that were luck look like.

| What held up | In sample | t | Out of sample | t | Events in / out |
|---|---|---|---|---|---|
| Taker NO against a 5 to 10c longshot loses | −5.1% | −3.2 | −8.4% | −4.4 | 383 / 150 |
| ... and against 5 to 20c longshots in markets with under $50 traded that week | −9.8% | −4.1 | −16.3% | −5.1 | 276 / 117 |
| Taker YES at 50c or more, 30 days before close, loses | −8.5% | −3.3 | −14.5% | −3.6 | 419 / 149 |

Selling longshots is the most solid result in the category so far: it loses on both sides of the split, on both
weightings, and loses most where the market is quietest. The other side of that trade, buying those thin
longshots, returns +22% in sample (t 1.2) and +61% out of sample (t 2.5; counted per event, t 1.7). That is a
lead with lottery-ticket variance: most bets lose everything, and it needs several times more events to judge.

The favourite loss is weaker counted per event out of sample (−8 to −9%, t about −2) than per bet: a few big
ladders carry part of it.

The buy-NO leads from 3.2 mostly faded. The one that strengthened is NO at 20 to 80 cents on markets listed 2 to
7 days ago, by resting order: nothing in sample (+2%, t 0.3), +51% out of sample (t 4.2). One half only, so it
stays a lead.

### 3.4 The Economics leads, year by year (19:55 UTC)

Before spending more rounds on the two leads left from 3.3, each was broken down by year, by series and by how
much of its profit comes from its five best events. Same data as 3.3.

| Lead | 2022 | 2023 | 2024 | 2025 | 2026 | Profit from 5 best events | Events that paid |
|---|---|---|---|---|---|---|---|
| Buy thin 5 to 20c longshots (taker) | +218% | +14% | +33% | −19% | +15% | 63% | 25% |
| Buy any 5 to 20c longshot (taker) | +65% | +6% | +31% | −29% | −12% | (net loss recently) | 24% |
| NO at 20 to 80c on markets listed 2 to 7 days ago (resting) | −18% | −10% | −5% | +3% | +30% | 49% | 49% |
| For comparison, the reliable loser: taker NO against 5 to 10c longshots | −9% | −4% | −9% | −2% | −6% | n/a | 83% |

**Both leads are dropped.** The longshot lead is 2022 and five events; it lost in 2025. The young-market lead is
2026 only and lost in every earlier year, which is the pattern of a stretch in which numbers came in low, not of
a pricing habit. The loser, by contrast, loses in every single year, with 83% of its events paying a little and
the rest costing a lot: that is what a real, small, persistent mispricing looks like, and it is on the wrong
side for anyone wanting a "safe" trade.

Where Economics stands after four looks: **no mechanical rule earns money after costs out of sample; two
"conservative" plays reliably lose it.** The engine now reports a year-by-year table for any lead before it is
followed further.

Operational note: this session's worker restarted around 19:10 UTC and killed both background jobs; the download
gained only 160 Politics markets in the hour. Both are restarted, a watchdog check-in now restarts them every
half hour, and the paper loop keeps its schedule in the ledger so a restart does not reset its clock.

### 3.5 Round r04, Politics added, and a flaw in the sample (21:00 UTC)

**Data.** Politics: 1,836 markets in 711 events. Combined with Economics: 5,080 markets, 1,565 events, 391,669
daily bars, 1,775 markets out of sample. 2,190 rules.

**What the round shows.** 1 pass, 49 leads, 50 reliably lose. Politics repeats the Economics pattern:

| Rule (taker unless noted), Economics + Politics | In sample | t | Out of sample | t | Events in / out |
|---|---|---|---|---|---|
| YES at 65 to 80c | −10.5% | −4.2 | −19.3% | −4.7 | 654 / 246 |
| YES at 80 to 90c | −7.6% | −4.1 | −15.4% | −4.6 | 569 / 215 |
| NO against a 5 to 10c longshot | −4.9% | −4.0 | −6.5% | −4.8 | 713 / 293 |
| YES at 0 to 5c, 14 to 30 days out | −65% | −6.6 | −81% | −7.6 | 414 / 166 |
| NO at 65 to 80c, resting order (the mirror of the first row) | +8.9% | 1.3 | +39.9% | 3.4 | 619 / 239 |
| NO against a 0 to 5c longshot, 14 to 30 days out, resting order (the one "pass") | +2.1% | 3.2 | +2.8% | 4.9 | 342 / 150 |

Read at face value: prices are too extreme between about 5 and 95 cents (the dear side loses), and the very
cheapest contracts, under 5 cents, are overpriced.

**Why I do not read it at face value.** Every market in these rounds was among the biggest of its category by
lifetime volume: the median market here traded 66,858 contracts. Lifetime volume is hindsight. A 10-cent
contract that goes on to win trades heavily on its way to a dollar; a 90-cent favourite that collapses does the
same. Choosing the biggest markets therefore over-samples surprises, and surprises are exactly "the dear side
lost". I checked whether the effect grows with volume inside this sample and it does not clearly (favourites:
−10%, −13%, −20%, −15% from the smaller half to the top 5%), but that proves little, because the whole sample is
the top of the distribution.

**What changed.** The download now takes markets in a fixed random order within each category, with no volume
minimum beyond "ever traded", and `research/panel.py` uses only the markets drawn that way. The 5,840 markets
already downloaded biggest-first stay in the database but are excluded by default. A test covers it. The random
Economics sample is downloading now; Politics follows.

**What stays.** The engine, the families, and the rule that any lead gets a year-by-year table. The forward test
of Claude's forecasts is unaffected.

**Also found:** this session's machine is put to sleep about two minutes after a turn ends unless a task tracked
by the session is still running. Detached jobs alone do not keep it awake. That is why the download stalled twice.
Each check-in now leaves a tracked keep-awake task running beside the download.
