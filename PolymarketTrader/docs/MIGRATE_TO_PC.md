# Moving the project to the PC

Written 2026-11-19, 3:08 am CST. The work so far was done in a cloud session that cannot reach the PC, so the
move is three steps you run yourself. Nothing here involves money, keys or accounts.

Target folder: `E:\Coding\PredictionMarketTrader` (change the path in the commands if you want it elsewhere; no
script depends on the folder's name or location).

## 1. Copy the project (PowerShell)

```
cd E:\Coding
git clone --depth 1 --branch claude/friendly-clarke-tf5rm4 --single-branch https://github.com/NoMansion/StockTrader.git _pmt_tmp
robocopy _pmt_tmp\PolymarketTrader PredictionMarketTrader /E
Remove-Item -Recurse -Force _pmt_tmp
```

If `E:\Coding\PredictionMarketTrader` already exists, the copy merges into it and overwrites files of the same
name; look at what is there first.

## 2. Put the data in place

The cloud session handed over one file, `PredictionMarketTrader_data.zip` (62 MB). It is not on GitHub: Kalshi's
terms do not allow republishing its data, and the repository is public. Unzip it into the project folder so that
its `data` folder becomes `E:\Coding\PredictionMarketTrader\data`:

```
Expand-Archive -Path $HOME\Downloads\PredictionMarketTrader_data.zip -DestinationPath E:\Coding\PredictionMarketTrader
```

| File | What it is | Without it |
|---|---|---|
| `data\pmt.db` | The paper account: 20 forecasts, 4 resting paper orders, $1,000 | A fresh paper account starts at the first cycle; the 20 forecasts are still in `reports\forward_log.csv` |
| `data\shadow.db` | Observation log of the longshot rule: 11 markets seen, 5 resting-order outcomes | Starts empty |
| `data\kalshi_hist.db` | Kalshi history for the backtests: 32,000 markets with daily prices, 355 MB unzipped | `research\kalshi_download.py` rebuilds it in about 12 hours |
| `data\kalshi_events.db` | Which events Kalshi flags as mutually exclusive (405 looked up) | Refetched on demand |
| `data\kalshi_listing.json`, `data\kalshi_series.json` | Caches of the live market list | Rebuilt at the first cycle (slow: Kalshi throttles the listing) |
| `data\cloud_config.yaml` | The settings the cloud cycles ran with | Not needed on the PC: use `config.yaml` |

The snapshot was taken at 3:06 am CST on 2026-11-19. Anything the cloud session did after that is not in it.

## 3. Install and check

```
cd E:\Coding\PredictionMarketTrader
Set-ExecutionPolicy -Scope Process Bypass; .\setup.ps1
.venv\Scripts\python scripts\status.py
```

`setup.ps1` builds the virtual environment, installs the packages, runs the tests and the offline demo.
`status.py` should show the paper account with its four resting orders.

**None of this has been run on Windows yet.** The code was written for it (hidden launcher, low priority, quiet
window around the stock trader's evening job, a lock file), but the first run is the test. If a step fails, the
error text is what a Claude session on the PC needs to fix it.

## Running it on the PC

- **One paper cycle by hand:** `.venv\Scripts\python scripts\run_cycle.py` (asks Claude for up to 4 forecasts;
  needs the `claude` command installed and signed in; several minutes).
- **Unattended, every 8 hours:** the `schtasks` line in `README.md`. The launcher also exports the forecast log,
  takes the observation log's readings and rewrites `data\status.md`.
- **Settings.** `config.yaml` asks for 3 Claude runs per forecast at high effort; the cloud cycles used 2 runs at
  medium effort (`data\cloud_config.yaml`). Either is fine, but pick one and keep it: a change of settings is a
  break in the track record, and `forward_log.csv` records which was used.
- **Backtests** (need the history database):
  ```
  .venv\Scripts\python research\panel.py
  .venv\Scripts\python research\run_sweep.py --round r15 --categories Economics,Politics --sample liquid
  .venv\Scripts\python research\analyze_rule.py --sample liquid --min-cumvol 5150 --categories Economics --rule "NO at mid <= 5c, <= 30d, spread <= 5c" --side no --entry mk
  ```
  `research\STATE.md` is the control sheet: what has been tested, the rules for judging a result, what is next.
- **More history:** `.venv\Scripts\python -u research\kalshi_download.py --interval 0.4 --first-pass 2500` resumes
  where the snapshot stopped (Commodities, then Financials, Mentions, Entertainment, Crypto, Social, Climate and
  Weather). It is paced for Kalshi's limits and uses little of the PC; it can be stopped and restarted at will.

## Keeping the two copies from diverging

- The paper account must run in ONE place. Once cycles run on the PC, the cloud paper loop has to stop, or two
  ledgers drift apart. Until you say the PC copy is running, the cloud one keeps going and its ledger is the
  record.
- Research that the cloud session commits after this snapshot reaches the PC with
  `.\scripts\sync_from_github.ps1`, which updates the code and reports and leaves `data\`, `.venv\` and `.env`
  alone.

## What does not move

- The hourly check-ins and the keep-awake arrangement belong to the cloud session. On the PC, the scheduled
  task replaces them for the paper bot; backtests run when you or a Claude session on the PC start them.
