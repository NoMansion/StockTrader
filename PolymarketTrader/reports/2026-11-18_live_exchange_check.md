# First contact with the live exchange
*Wednesday 2026-11-18, about 11:00 UTC. Read-only, public endpoints of gateway.polymarket.us. No account, no keys.*

## Summary

- **The bot works end to end on real data.** Two paper cycles ran against the live exchange with Claude
  forecasting through the Claude Code command line: four markets forecast, no trades, as the rules intend.
- **Claude's numbers landed close to the market's.** The four gaps were +6, −0.5, +1 and +7 points. None reached
  the 10 points the rules need before trading. That matches the research: near the market, rarely far from it.
- **The legal venue is thin outside sports, and this changes the plan.** Of 5,548 open non-sports markets in the
  allowed categories, only 12 have $50 or more resting near the price, and 7 of those have traded $1,000 or more.
  The go-live gate of 150 resolved events will take many months on this venue alone.
- **Several of my assumptions about the API were wrong and are now fixed**, and three that mattered for money
  were confirmed (settlement meaning, fee, the unsettled-market answer).

## What the exchange looks like

| | Count |
|---|---|
| Open markets, all categories | 19,110 in the first 3,000 events; sports alone is 4,464 events |
| Open markets in macro, finance, technology, politics, geopolitics, science | 5,548 |
| ... with a two-sided quote | about 1,500 |
| ... 3 to 75 days out, spread 4 cents or less, priced 15 to 85 cents, not on the title deny list | 96 (67 after two per event) |
| ... of those 67, with $5 or more resting within 2 cents of the price | 28 |
| ... with $50 or more resting and $1,000 or more traded (the trade tier) | 6 or 7, depending on the minute (12 have the depth alone) |

Among the 95 tightly quoted candidates, the median market had **$1** resting within 2 cents of the price and
**$48** traded in total. Quotes are tight because market makers post them; almost nobody is trading against them.

What passes the trade tier today: November CPI thresholds, year-end unemployment, year-end gas prices, and one
technology market. Corporate earnings, central-bank and ship-traffic markets pass the forecast tier only.

## What this means

1. **Small orders are large here.** A $20 order is 4% to 40% of what rests near the price in the deepest
   non-sports markets. Orders are now capped at 25% of nearby depth (`execution.max_depth_share`).
2. **Forecasts and trades are now separate tiers.** Markets with a real two-sided price are forecast and scored
   against that price even when they are too thin to trade (`universe.forecast_untradable`). That builds the
   evidence the gates need several times faster than waiting for tradable markets, at no trading risk. A price
   nobody trades is a weaker benchmark than a busy one, so read early Brier comparisons with that in mind.
3. **The gates will be slow.** With roughly 30 forecastable markets in about 20 events at a time, resolving every
   two to ten weeks, 150 resolved events is most of a year. Options, in the order I would take them:
   - keep the gates and accept the pace (nothing is at risk while paper trading);
   - add Kalshi as a second paper venue (deeper macro and politics books; needs an adapter and its API host);
   - widen to culture and sports markets, which is where this exchange's liquidity is (the research argues
     against both, so only for scoring, not trading).
4. **Fees matter less than expected, depth more.** With resting orders the 0.095 taker fee is never paid. The
   binding constraint on this venue is whether anyone will sell to a resting bid at all.

## Checked against the live API

| Assumption | Result |
|---|---|
| Settlement value is the YES payout | Confirmed on 14 settled markets: `settlement` 0 or 1 matches the YES side's final price |
| Settlement of an open market | HTTP 404 "Settlement not found", which the bot reads as "not settled yet" |
| Taker fee coefficient 0.095 | Confirmed: `feeCoefficient` is 0.095 on all 19,110 listed markets. Now read per market |
| Tick size 0.01 | Wrong for 3% of markets (0.001, 0.0025, 0.005). Now read per market (`orderPriceMinTickSize`) |
| Minimum order | 0.01 contracts on most markets, 1 on some (`minimumTradeQty`). Now enforced per market |
| Listings carry liquidity and volume | Wrong. They carry quotes only; traded dollars and open interest come with the order book |
| Market detail names its event | Wrong. Only the listing does; the bot now keeps the event from the listing |
| Category names | sports, politics, culture, macro, technology, crypto, finance, geopolitics, science, climate |
| Category filter | Works on the server (`categories`), so sports is never downloaded |
| The long side is YES | Confirmed (`marketSides[].long` with description "Yes") |
| A resolved market is flagged `closed` | Mostly; 19 of 350 resolved markets had `closed: false`. The bot now also reads `status` |
| Request pacing of 2 a second is fine | Wrong. The gateway answered HTTP 429 after bursts. Now 1 a second with a back-off |

Real payloads are saved in `tests/fixtures/` and parsed by a test.

## The four real forecasts

| Market | Claude (2 runs) | Market mid | Gap | Decision |
|---|---|---|---|---|
| CPI month-over-month in November above −0.2% | 0.895 (0.87, 0.92) | 0.835 | +6.0 | no trade: blended edge 2.3 points, needs 3 |
| CPI year-over-year in November above 3.6% | 0.790 (0.78, 0.80) | 0.795 | −0.5 | no trade |
| #1 AI model at end of 2026: Google | 0.755 (0.74, 0.77) | 0.745 | +1.0 | no trade (this kind of market is now excluded: see below) |
| Unemployment as low as 4.0% by year end | 0.315 (0.30, 0.33) | 0.245 | +7.0 | no trade: blended edge 2.6 points |

These came from a trial run with reduced settings (2 runs, medium effort) on a throwaway ledger. Each run took
about 100 seconds and the two-run forecasts used roughly $0.26 to $0.63 of Claude usage each at list prices. The
rationales read the rules closely (for example, noticing that a one-decimal CPI print makes "above −0.2%" mean
"−0.1% or higher") and cite primary sources. Whether they are *right* will be known in December.

## Two judgment calls made here

- **Markets about AI models and their makers are excluded** (`title_deny`). The forecaster is one of the models
  being ranked; it should not be betting on that. This removes about 200 markets, which is nearly all of
  the technology category and includes its most liquid market.
- **Personnel markets are excluded** ("who will leave office", "announced out of their role"): the research
  found insider trading concentrated in exactly these.

## Still not verified

- Anything that needs an account: order placement, how a NO order's price is expressed, post-only behaviour,
  the fee actually charged on a fill.
- Whether the exchange accepts an account from every state (the sign-up check is the only authority).
- How often resting orders at these depths would really fill. The paper rule (filled only when the ask comes down
  to the order) is pessimistic by design, and in markets this quiet it may rarely trigger.
