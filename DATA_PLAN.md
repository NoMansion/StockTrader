# Data source and cleaning plan

## Decision: Norgate Data, Platinum (Windows)

| Role | Source | Cost (Nov 2026) | Why |
|---|---|---|---|
| **Research + live bars** | **Norgate Data — US Stocks, Platinum** | $630/yr ($346.50/6 mo) | History to 1990, **delisted securities included**, **historical index constituents** (S&P 500, Russell 1000/2000/3000, NASDAQ 100…), total-return adjusted prices, GICS sectors, basic fundamentals. Python package on PyPI. Requires the Norgate Data Updater app running on Windows 10/11. |
| **Execution + live quotes** | **Alpaca** | free | Paper trading, order API, intraday quotes if ever needed. |
| **Dev / smoke tests** | yfinance | free | Confirms the pipeline runs; never trust its backtest numbers. |

Why Platinum and not Gold: Gold ($360/yr) has no delisted securities and no
index history — it would leave the backtest survivorship-biased, which is the
whole thing we're paying to fix. Diamond ($787.50/yr) only adds history back
to 1950, which doesn't matter for a daily ML strategy.

Alternatives kept on file: Sharadar ($299/yr prices, $499/yr bundle, REST
API, Linux-friendly) is the swap if the bot ever moves off Windows; its index
history covers only the S&P 500. Tiingo (~$10/mo) is cheap clean EOD without
delisted coverage. EODHD, Polygon, Databento, CRSP: see earlier notes.

### Norgate specifics that shape the design

- **Deployment is Windows.** NDU must be running for every data pull, so the
  daily job runs on your PC (Task Scheduler) or a Windows VPS, not a Linux box.
- **Permanent id**: `norgatedata.assetid(symbol)` — key everything on it, not
  the ticker. `src/providers_norgate.py` already attaches it.
- **Delisted names** live in a separate database, `"US Equities Delisted"`.
  Always load both (`list_symbols(include_delisted=True)`).
- **Delisting date**: `last_quoted_date(symbol)`; None means still listed.
- **Index membership**: `index_constituent_timeseries(symbol, "Russell 1000", …)`
  gives a per-day 0/1 column. `point_in_time_universe()` stacks these into a
  date × ticker matrix the backtest uses to decide who is tradable each day.
- **Adjustments**: request `TOTALRETURN` for features/labels and `NONE` for the
  raw close used in order sizing; the provider pulls both.
- **Padding**: use `PaddingType.NONE` and do calendar alignment ourselves
  (step 2 below) so imputed bars are explicit.

Run `python scripts/norgate_smoke.py` first on the PC: it reports whether the
delisted database and index history are actually unlocked by your subscription.

## Data model

Store one tidy **long** table of daily bars, partitioned by year, Parquet:

```
date | ticker | open | high | low | close | volume | adj_close | adj_factor | is_active
```

Plus three reference tables:

- `securities`: ticker, permanent id (CUSIP/FIGI/vendor id), name, exchange, sector, first_date, last_date, delist_reason
- `corporate_actions`: date, ticker, type (split/dividend/spinoff/symbol_change), ratio/amount
- `universe_membership` (point-in-time): date_from, date_to, ticker, index_name

**Key principle: key everything on a permanent security id, not the ticker.** Tickers get reused (the "FB"→"META" problem in reverse). The vendor supplies this; yfinance doesn't.

## Cleaning pipeline (in order)

Each step is a function in `src/cleaning.py`; each writes a report of what it changed. Never fix data silently.

### 1. Ingest raw, keep raw
Land vendor files untouched in `data/raw/<vendor>/<date>/`. Cleaning always reruns from raw. Vendors restate history; you want to see diffs.

### 2. Calendar alignment
- Build the NYSE trading calendar (`pandas_market_calendars`); reindex every ticker to it.
- Missing bar on a trading day while the security is active → flag `gap`. One-off gaps: forward-fill `close`, set `volume=0`, mark `imputed=True`. Runs of >5 gaps → treat as not tradable for that span.
- Bars on non-trading days → drop and log (usually vendor error).

### 3. Corporate-action adjustment
- Rebuild `adj_close` yourself from raw close + the actions table rather than trusting the vendor's adjusted column. Cross-check against vendor's; differences >0.5% go in the report.
- Returns for features/labels use **total return** (dividends reinvested). Order sizing uses **raw close** (what you actually pay).
- Verify splits: a day with |return| > 40% and a split on that date in the actions table is fine; without one it's a data error or a real event — flag for manual review.

### 4. Bad-print filter
- Drop or null bars with `high < low`, `close` outside `[low, high]`, zero/negative prices, or volume < 0.
- Flag single-day returns > 50% that revert next day (classic bad print).

### 5. Delistings and survivorship
- Keep every security that ever existed in the universe window.
- On the delist date, apply a **delisting return**: use vendor's if provided; otherwise −30% for bankruptcies/performance delistings (CRSP-style convention), 0% for mergers at the last price. Document the choice; it moves results.
- After delisting, the security is not purchasable: `is_active=False`.

### 6. Point-in-time universe
- Define the tradable universe each day from rules evaluated **only on data available that day**: e.g. top 1,000 by 60-day median dollar volume, price > $5, listed on NYSE/NASDAQ, `is_active`.
- Recompute membership monthly, snapshot it, and store it. Never filter by "is in the S&P 500 today."

### 7. Feature-time safety (lookahead audit)
- Every feature at date *t* must use bars ≤ *t*. Labels use bars > *t*.
- Fundamentals: shift by their **filing/availability date**, not period end (Sharadar provides `datekey` for this).
- Unit test: perturb the future (shuffle bars after *t*) and assert features at *t* don't change.

### 8. Outlier handling for the model
- Winsorize features at the 1st/99th percentile **per date** (cross-sectional), then rank-normalize to [0,1] per date.
- Winsorize labels (forward returns) at ±3 sigma per date.
- Never winsorize prices themselves.

### 9. Validation report (run on every refresh)
- Row counts per year vs. prior refresh (big drops = vendor outage).
- Per-ticker: first/last date, % imputed bars, number of flagged prints.
- Universe size per month (should be stable, not sawtoothed).
- Reconcile 20 random tickers' latest close against a second source (Alpaca) within 0.1%.

### 10. Refresh cadence
- Nightly incremental pull after close; full rebuild weekly (vendors restate).
- Live loop uses the same cleaning code as the backtest. One code path, or the backtest is testing something you don't trade.

## Order of implementation

Done in the starter:
- Norgate provider with total-return + raw close and `assetid` (`src/providers_norgate.py`)
- Point-in-time universe from index constituents (`universe: norgate`) and a
  rule-based alternative (`universe: liquidity`) — step 6
- Membership enforced in backtest and live job: non-members are scored out
  and sold
- Lookahead unit tests for features and for the liquidity universe — step 7
- Bad-print filter — step 4 (minimal)

Next, in order:
1. Step 2: NYSE calendar alignment with explicit `imputed` flags.
2. Step 5: delisting returns using `last_quoted_date` + the security master.
3. Step 3: rebuild adjustments from Norgate's capital-event series and
   cross-check against its adjusted close; report differences.
4. Step 9: the validation report, run by `fetch_data.py` on every refresh.
5. Fundamentals as features (`norgatedata.fundamental(symbol, field)`), with
   availability-date shifting — this is where Norgate's data adds model inputs.

Items 1–2 are a couple of evenings. Item 3 is where most people cut corners; don't.

## Sources

- [Survivorship-Bias-Free Equity Data: 9 Vendors Compared (Frontier Ledger, June 2026)](https://frontierledger.ai/strategy-backtesting-evaluation/survivorship-bias-free-equity-universes-data-vendors-compared)
- [Sharadar — Subscribe](https://sharadar.com/subscribe)
- [Norgate Data — Stock Market Packages](https://norgatedata.com/stockmarketpackages.php)
- [norgatedata on PyPI (API and system requirements)](https://pypi.org/project/norgatedata/)
- [Tiingo vs Polygon for indie quant projects (2026)](https://dev.to/pickuma/tiingo-vs-polygonio-market-data-apis-for-indie-quant-projects-in-2026-2j2e)
- [EODHD delisted companies data](https://eodhd.com/financial-apis/delisted-stock-companies-data-2)
- [Alpaca Market Data](https://alpaca.markets/docs/market-data)
