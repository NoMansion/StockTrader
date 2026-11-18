# Strategy research on Kalshi history
*Started Wednesday 2026-11-18. A running report: newest status first, then method, then one dated section per
round. Nothing here has been traded, on paper or otherwise.*

## Status

*Updated 4:40 pm CST, 2026-11-18. Times in new text are US Central; sections 3.1 to 3.5 were written in UTC.*

- **One mechanical result has held up: in busy markets, cheap YES contracts are overpriced, and buying NO
  against them has paid.** Where YES is quoted at 5 cents or less in a market that has already traded 45,000
  contracts, buying NO earned about +1.4% per bet paying the ask and about +3% with a resting order, positive in
  both halves of the data, in Economics and in Politics, with 7 losing events out of 524. It matches published
  work on Kalshi. Sections 3.7 and 3.8.
- **It is small and lopsided.** Each bet risks about 97 cents to make 2 or 3. Replayed through an account at 1%
  stakes it returned about 1% a year before 2026 and about 9% a year in the last six months, with a fifth of the
  money at work. On a $1,000 account that is tens of dollars a year. It is not yet in the paper bot (section 3.9).
- **Nothing else passes.** On a random sample of all markets no rule passes, and the "expensive side loses"
  pattern of rounds 3.2 to 3.5 is gone: it came from the way those markets were chosen (section 3.6).
- **Two flaws of mine found and fixed today:** markets chosen by lifetime volume (3.5), and "days to close"
  measured from a close date that was not knowable in advance (3.7). Rounds 3.1 to 3.5 are superseded.
- **Forward test of Claude's forecasts:** two paper cycles, 8 forecasts, 6 of them low-confidence and not
  traded, one resting paper order, account at $1,000 (`reports/forward_log.csv`).
- **Still to come:** Companies, Commodities, Science and Technology, Elections, Health and World are
  downloading in that order; each gets the same rounds.

## 1. Method

**Data.** Settled Kalshi markets from the exchange's public archive (2021 to September 2026) plus markets settled
since, with daily bars of bid, ask and traded price. Since 20:53 UTC on 2026-11-18 the download draws markets in a fixed random order within each category and
takes any market that ever traded; backtests use only that random sample. (Before that it took the biggest
markets first, with a 200-contract minimum: see section 3.5 for why that was a mistake.) Liquidity conditions in
a rule must use volume as it stood at the time of the bar, never lifetime volume.

**Two samples, and only these two** (since 4:00 pm CST on 2026-11-18):
- *Random:* markets in a fixed random order, any market that ever traded. It represents the whole exchange,
  which is mostly tiny markets with wide quotes.
- *Busy markets:* every market that ever reached a set number of contracts traded, seen only from the day it
  reached it. A rule never sees the quiet early days of a market that later became big, so there is no hindsight
  in the choice. The level is 13,100 contracts for Economics alone and 45,000 where Politics is included; the
  download is extending it down to 5,000.

**Days to close come from the schedule.** Kalshi overwrites a market's close time when it closes early, so for
markets that can close early the backtest counts days to the expected expiration, which was known in advance.
Holding times and account replays use the real close.

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
- *Lopsided bets get a different test.* A t-statistic means little for a bet that wins 2 cents 99 times and loses
  97 cents once. For those, `research/analyze_rule.py` counts losing events, works out the loss rate at which
  the rule breaks even, and asks whether an exact 95% upper bound on the true loss rate is still below it.

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
| 16 | Early close | Markets that can close early against fixed-date ones (uninformative: 82 to 99% carry the flag) |
| 18 | Question shape | "Above X", "below X", "between", or no number |
| 19 | Event size | Longshots and favourites by the number of outcomes in the event |
| 22 | Event price sums | Outcomes of one event priced to more or less than 1 in total |
| 23 | Traded so far | Price bands by contracts traded up to that day |
| 24 | Share of life | Price bands by how much of the scheduled life has passed |
| 25 | Longshot crosses | NO under 15c crossed with days left, momentum, volume, spread, favourite |
| 26 | Dear side | The favourite-longshot bias as one rule: buy the expensive side when the cheap side is under x |
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

### 3.6 Round r07 on the random sample: the earlier pattern is gone (4:40 pm CST)

**Data.** The random draw: Economics 1,948 markets in 1,076 events (complete first pass); Politics 1,039 markets
in 684 events (first pass 40% done). About 2,730 rules each.

**Result.** No rule passes in either category.

| YES price, random Economics | YES taker in / out | NO taker in / out | Events in / out |
|---|---|---|---|
| 5 to 10c | −4.9% / +0.4% | −5.6% / −6.8% | 179 / 143 |
| 10 to 20c | −4.5% / −8.2% | −5.7% / −7.9% | 170 / 120 |
| 20 to 35c | −6.3% / +0.1% | −6.0% / −9.1% | 170 / 113 |
| 65 to 80c | −1.1% / −4.1% | −18.6% / −16.0% | 155 / 118 |
| 80 to 90c | −0.8% / −8.2% | −35.8% / +4.1% | 143 / 105 |

- *"Taker YES at 65 to 90c loses" (rounds 3.2 to 3.5):* not confirmed. −1% in sample, −4% to −8% out, neither
  significant. The −10% to −19% of round r04 came from choosing markets by lifetime volume.
- *"Taker NO against 5 to 20c longshots loses":* still negative (−6% to −8%, t about −2.5 to −3), but so is
  every other taker bet here. In the typical Kalshi market the quote is wide and thin, and anyone paying the ask
  on either side loses roughly the spread and the fee. That is a statement about costs, not about mispricing.
- Random Politics looks different from random Economics: cheap YES loses heavily there too (YES at 0 to 5c:
  −71% / −100%; NO against it: +0.6% / +2.2%), the same shape as in the busy markets below.

### 3.7 Round r07 on busy markets: cheap YES is overpriced (4:40 pm CST)

**Why a second sample.** The bot would only ever trade busy markets, and a random draw of 2,500 holds few of
them. The 5,840 markets downloaded biggest-first are exactly the busy ones; what made them unusable was that
rules also saw their early days, before anyone could know they would become big. The busy-market sample keeps a
market only from the day it had traded the set level. Checked: a market's daily bars add up to at most 1.023
times its lifetime volume, so with a 3% margin no market that qualified is missing.

**A second flaw, found on the way.** For a market that closed early, Kalshi's archive shows the early close as
its close time. "At most 30 days to close" then selects the days just before something happened. The download
now keeps each market's expected expiration and the backtest counts days to that. It mattered most in Politics,
where 36% of the yes-resolving markets had closed more than 3 days early. All numbers below are after the fix.

**Data.** Economics and Politics at the 45,000-contract level: 3,313 markets in 1,105 events, 120,938 daily
bars, 1,045 markets out of sample. 2,931 rules: 22 pass, 49 leads, 43 reliably lose. Every pass and every
lead is the same idea: buy NO.

| YES price | YES taker in / out | NO taker in / out | YES resting in / out | NO resting in / out | Events in / out |
|---|---|---|---|---|---|
| 0 to 5c | −73.9% / −75.7% | +1.2% / +1.0% | −78.1% / −80.4% | +2.9% / +2.7% | 464 / 168 |
| 5 to 10c | −66.9% / −52.4% | +2.6% / +2.2% | −57.2% / −47.3% | +5.4% / +4.4% | 409 / 132 |
| 10 to 20c | −44.9% / −33.1% | +3.7% / +1.4% | −43.9% / −18.0% | +7.4% / +4.5% | 375 / 122 |
| 20 to 35c | −24.9% / −27.4% | +2.1% / +4.2% | −16.1% / −22.9% | +5.9% / +7.6% | 345 / 110 |
| 35 to 50c | −14.9% / −13.2% | +0.2% / +0.2% | −11.7% / −8.0% | +3.9% / +1.4% | 287 / 80 |
| 50 to 65c | −9.2% / −6.6% | −2.6% / −3.3% | −5.3% / −1.7% | +3.8% / +5.4% | 271 / 80 |
| 65 to 80c | −4.5% / −4.9% | −9.8% / −10.1% | −2.2% / −0.9% | −2.8% / +2.2% | 267 / 79 |
| 80 to 90c | −0.2% / −3.0% | −24.3% / −8.8% | +2.4% / −1.3% | −13.0% / +3.2% | 262 / 84 |
| 90 to 95c | +0.8% / +0.2% | −39.4% / −36.0% | +3.0% / +3.3% | −23.6% / −9.4% | 251 / 78 |
| 95 to 100c | +0.9% / −1.4% | −71.6% / −45.8% | +2.3% / −0.2% | −63.2% / +2.6% | 285 / 80 |

**How to read it.** Whoever buys the cheap side loses, on either side of the book: YES under 35 cents and NO
under 10 cents (the last three rows) both lose heavily. This is the favourite-longshot bias, and it is what
Bürgi, Deng and Whelan report for Kalshi ("Makers and Takers", cited in the strategy report). The other side of those trades earns something only on one side:
buying NO against a cheap YES is positive in every band under 35 cents, in and out of sample, while buying YES
against a cheap NO is about zero. So there is also a general lean toward YES being overpriced.

**The rules that pass,** all "buy NO where YES is very cheap":

| Rule (busy markets, Economics + Politics) | Entry | In sample | t | Out of sample | t | Win rate out | Events in / out |
|---|---|---|---|---|---|---|---|
| YES at 5c or less, 30 days or less to go, spread 5c or less | taker | +1.3% | 3.2 | +1.7% | 4.7 | 99.7% | 392 / 150 |
| same | resting | +3.0% | 6.4 | +3.2% | 6.9 | 99.6% | 324 / 134 |
| YES at 3 to 6c, spread 1c | taker | +2.5% | 5.1 | +3.1% | 4.7 | 99.1% | 336 / 124 |
| YES at 3 to 6c, fell 1c or more in a day | resting | +4.2% | 6.8 | +4.3% | 5.3 | 98.9% | 295 / 104 |
| YES at 10c or less, 30 days or less to go (a lead: weak when each event counts once) | resting | +3.8% | 5.2 | +3.7% | 4.1 | 98.2% | 367 / 149 |
| YES at 5 to 35c, any time (a lead) | resting | +6.0% | 3.4 | +6.0% | 2.1 | 85.3% | 486 / 159 |

Economics alone at the lower 13,100-contract level shows the same (8 pass, all of this kind). The busy-market
condition matters: in random Economics, most of which is thin, the same bets lose 2% to 6%.

### 3.8 The 5-cent rule taken apart (4:40 pm CST)

Rule: busy market, YES at 5 cents or less, spread 5 cents or less, 30 days or less to the scheduled end; buy NO.

| | Taker | Resting order |
|---|---|---|
| Bets, events | 914 in 524 | 736 in 443 |
| Mean return per bet | +1.41% | +3.06% |
| Losing bets | 7 | 6 |
| Losing events in / out of sample | 6 of 392 / 1 of 150 | 5 of 324 / 1 of 134 |
| Break-even loss rate (events) | 3.8% | 6.2% |
| 95% upper bound on the true loss rate | 2.5% | 2.7% |
| Median holding time | 13 days | 13 days |
| Account replay at 1% stakes, before April 2026 (4.4 years) | +0.8% a year, 3% of money at work | +2.3% a year |
| Account replay at 1% stakes, April to September 2026 | +8.6% a year, 17% at work, worst drawdown 1.0% | +13.5% a year |

The tail test passes in both halves: even the pessimistic loss rate is below break-even.

**What to hold against it.**
- *All seven losses are in 2025 and 2026*, five of them in 2025, when the taker version made +0.4% per bet:
  about nothing. Before 2025 there are only 85 bets. So the evidence is two years, one of them flat.
- *Losses come together.* A surprise in one event takes out every longshot NO in it; a broad shock could take
  out several events. The replay's 1% drawdown has not seen that.
- *Resting-order fills are modelled*, from daily highs and lows. The +3% depends on that model; the +1.4%
  taker figure does not.
- *Size.* On the entry day the median market traded 3,300 contracts; one in eight traded under 100. Fine for
  $20 orders, not for much more in the smaller ones.
- *Dollars.* 220 to 265 bets in the last half year at $10 to $20 each is a few dollars a month on $1,000.
- *Two categories, five and a half months out of sample.*

### 3.9 Forward: what was started, and what was not changed (4:40 pm CST)

- **Observation log, no orders.** `scripts/shadow_longshot.py` looks at live Kalshi markets that meet the
  5-cent rule and records the quote, the contracts resting at the NO ask, what a $20 order would have paid on
  that book, and later the settlement. First run: 17 candidates in Economics and Politics, 11 qualified. Dollars
  resting at the NO ask: $50 at the 10th percentile, $113 at the 25th, $3,466 at the median, $16,463 at the
  75th. A $20 order would have filled in full on all 11. It runs after every paper cycle. This is the check the
  backtest cannot do: Kalshi's history has no order books.
- **The paper bot is unchanged.** The rule buys at 95 to 99 cents; the bot's `sizing.max_price` is 0.88 and its
  universe stops at 85 cents. Raising either because a backtest looks good is what I said I would not do. If you
  want the rule traded on paper, the clean way is a second paper account with its own limits, so the forecast
  test and the rule test do not mix. That is your call.
- **Paper cycles.** 12:52 pm: 4 forecasts, 1 resting order (NO on the December 12 shutdown market, $20 at 65c).
  3:56 pm: 4 forecasts, no order (3 low confidence, 1 edge of 0.9 points against the 3 required). Six of eight
  forecasts were marked low-confidence by the forecaster itself. The order has not filled.

