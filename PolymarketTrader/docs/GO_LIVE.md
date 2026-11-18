# Going live: what has to be true first

Real-money trading is not implemented. `account.mode: live` raises an error by design, and `LiveBroker` in
`src/broker.py` is a stub. This page is the list of things that must hold before that changes, written before the
first forecast so the bar cannot drift once results start coming in.

## 1. The paper record passes every gate

`scripts/status.py` prints these under "Go-live gates". They are defined in `src/scoring.py` (`GATES`).

| Gate | Threshold | Why |
|---|---|---|
| Forward paper trading | 8 weeks | Shorter records are dominated by a handful of events. |
| Resolved events with a forecast | 150 distinct events | Fewer cannot separate skill from luck on a Brier comparison. |
| Price-movement observations | 200 forecasts with a price 72 hours later | The fastest signal of edge; needs volume to mean anything. |
| Market moves toward the model | t-statistic of 2 or more | If prices do not drift toward Claude's number, there is no edge to trade. |
| Not worse than the market price | Brier t-statistic above −2 | A forecaster that is measurably worse than the price should not trade against it. |
| Paper profit after costs | at or above zero | With pessimistic fills. Paper overstates live results; a paper loss will not become a live gain. |

All six are required. Also required, and not automated: four straight weeks with no unexplained cycle errors, and
no held market resolved in a way the forecaster's rules summary did not anticipate.

These gates were set before the exchange had been seen. The first live scan (2026-11-18) found only about 30
forecastable non-sports markets at a time, so 150 resolved events is most of a year on this venue alone. The
gates stay as they are: the honest options are to wait, or to add a second venue with deeper books (Kalshi), not
to lower the bar. If the evidence after 100 resolved events points clearly the wrong way (the model measurably
worse than the price), stop early and keep the log.

## 2. The venue has been checked by hand

- [ ] Polymarket US accepts an account from your state (the sign-up eligibility check is the only authority;
      sources disagree about several states). If it does not, the venue is Kalshi and a new adapter is needed.
- [x] Fee: `feeCoefficient` was 0.095 on every listed market on 2026-11-18, and the bot reads it per market.
      Re-read docs.polymarket.us/fees for volume tiers and any change before funding.
- [x] Tick size and minimum quantity are read per market from the exchange (`orderPriceMinTickSize`,
      `minimumTradeQty`).
- [x] `markets.settlement` on an open market answers 404; on a settled one, the YES payout (0 or 1).
- [ ] The exchange rulebook's settlement and dispute process has been read.
- [ ] The API terms allow automated trading on your own account (third-party guides say yes; read the terms).
- [ ] How a NO ("short") order's price is expressed has been confirmed with `orders.preview` on a real market.
- [ ] Post-only orders (`participateDontInitiate`) behave as expected, and a rejected one is recognisable.

## 3. Keys

- The exchange API key is created at polymarket.us/developer after identity verification. It is an Ed25519 key
  pair; the secret is shown once.
- **Do not put it in `.env`.** Project-local `.env` files are exactly where the documented key stealers look.
  Store it in Windows Credential Manager and load it at run time.
- Fund the account with the experiment's stake only. $200 to $500 is enough to learn everything the first live
  phase can teach.
- Never install a third-party Polymarket bot, skill, MCP server or "connector" on the machine that holds the key.
  Install only the packages in `requirements.txt`, by exact name and version.

## 4. What then gets built

1. `LiveBroker` on the official `polymarket-us` SDK: post-only limit orders (`participateDontInitiate`), every
   order sent through `orders.preview` first and refused if the previewed cost differs from the plan, order
   placement never retried automatically, `manualOrderIndicator` set to automatic.
2. Reconciliation at the start of every cycle: the exchange's positions and balance against the ledger. Any
   difference stops trading.
3. Cancel-all on start-up, on shutdown and on any safety stop.
4. A dry-run mode that previews orders without sending them, run for a week alongside the paper account.

## 5. The first live phase

- $200 to $500. Positions of $5 to $10. `safety.max_order_usd` set to match.
- `PMT_LIVE_CONFIRM=yes-real-money` in the environment, alongside `account.mode: live`.
- A person approves each of the first 20 to 30 orders.
- Every live fill is compared with what the paper simulator assumed for the same order.
- Scale in steps of at most double, only after 200 live trades with positive price movement toward entries and
  non-negative profit. Ceiling for this experiment: $2,000 to $5,000.

## Stop conditions, live or paper

- Price movement significantly against the model after 100 forecasts.
- The model's Brier score significantly worse than the market's.
- 25% of deposited money lost (enforced in `src/safety.py`).
- Any sign of a leaked key, or the ledger and the exchange disagreeing.
- A change in the venue's legal status in your state.

## Tax

The IRS has not said how event contracts are taxed. Keep the ledger (`data/pmt.db` holds every fill, fee and
settlement with timestamps) and ask a tax professional before filing.
