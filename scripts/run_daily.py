"""The daily job: pull latest bars, score, apply rules, send orders.

Run after the close (config: live.schedule_local_time). With live.order_type "opg" the orders go to the next
opening auction (whole shares, sub-share rest as small DAY orders); Alpaca only accepts auction orders before
09:28 or after 19:00 ET, so the run computes everything first and then waits for 19:01 ET before sending.

    python scripts/run_daily.py --dry-run          # no orders: a paper copy of the Alpaca account (read-only)
    python scripts/run_daily.py                    # Alpaca paper (keys in .env)

State (exit dates for the re-entry cooldown, last rebalance) persists in data/live_state.json. The weights the
rules start from are the account's ACTUAL weights (positions / equity), the live twin of the backtest's
drift_weights: the no-trade band (portfolio.min_trade_pct) then leaves drifted names alone instead of re-trading
every name to yesterday's target (bug audit 2026-11-13).

Safety: the run stops before any order if the price data is not current (last bar is not the latest completed
session, or far fewer names have a bar today than yesterday), on a market holiday it exits quietly, and every
failure that skips or degrades the day is written to data/run_daily_errors.log.
"""
import argparse
import gc
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import _bootstrap  # noqa: F401
from dataclasses import replace

from src.backtest import BacktestConfig
from src.books import book_rules, build_books, combine_weights, single_book
from src.config import build_cost_model, build_rules, load_config
from src.costs import dollar_adv
from src.dataset import load_dataset
from src.exposure import exposure_series, scale_rules
from src.features import compute_features, forward_excess_return, realized_vol
from src.memguard import start_guard, stop_guard
from src.providers_sharadar import fundamentals_from_config
from src.portfolio import State, drift_weights, rebalance
from src.ranking import make_ranker, trailing_ic
from src.sectors import load_sectors
from src.universe import apply_membership, trade_membership, trim_to_universe

STATE_PATH = Path("data/live_state.json")
ERROR_LOG = Path("data/run_daily_errors.log")
ET = ZoneInfo("America/New_York")
OPG_CLOSED = (dtime(9, 28), dtime(19, 0))     # Alpaca rejects OPG orders submitted in this window (ET)


class DataNotCurrent(RuntimeError):
    pass


def log_error(msg: str, path: Path = ERROR_LOG) -> None:
    print("ERROR: " + msg, flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file + rename, so a crash mid-write never leaves a truncated state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def trading_sessions(start: date, end: date) -> list[date] | None:
    """Exchange sessions from Alpaca's calendar (read-only); None if it cannot be reached."""
    try:
        from alpaca.trading.requests import GetCalendarRequest
        from src.broker import AlpacaBroker
        cal = AlpacaBroker().client.get_calendar(GetCalendarRequest(start=start, end=end))
        return [pd.Timestamp(c.date).date() for c in cal]
    except Exception as e:   # noqa: BLE001
        print(f"Alpaca calendar unavailable ({type(e).__name__}); using weekdays", flush=True)
        return None


def expected_last_session(now_et: datetime, sessions: list[date] | None) -> date:
    """The latest session whose close (16:00 ET) has passed. Without a calendar: the latest weekday."""
    d = now_et.date()
    if sessions is None:
        sessions = [x.date() for x in pd.bdate_range(d - pd.Timedelta(days=10), d)]
    done = [s for s in sessions if s < d or (s == d and now_et.time() >= dtime(16, 0))]
    return max(done)


def check_data(close: pd.DataFrame, expected: date, min_ratio: float = 0.9) -> None:
    """Raise DataNotCurrent if the last bar is older than `expected` or today's cross-section is incomplete."""
    last = close.index[-1].date()
    if last < expected:
        raise DataNotCurrent(f"price data ends {last}, the latest completed session is {expected} (Norgate not updated yet?)")
    if len(close) >= 2:
        n_now, n_prev = int(close.iloc[-1].notna().sum()), int(close.iloc[-2].notna().sum())
        if n_prev and n_now < min_ratio * n_prev:
            raise DataNotCurrent(f"only {n_now} names have a bar on {last} vs {n_prev} the session before (partial update?)")


def account_weights(pos: pd.Series, eq: float, exclude: set) -> pd.Series:
    """Actual stock weights in the account: market value / equity, sleeve ETFs excluded."""
    w = (pos / eq) if eq > 0 else pos * 0.0
    w = w[(w.abs() > 1e-9) & ~w.index.isin(list(exclude))]
    return w.astype(float)


def drifted(weights: pd.Series, close: pd.DataFrame, since: pd.Timestamp | None, today: pd.Timestamp) -> pd.Series:
    """Saved weights drifted with daily returns from `since` (exclusive) to `today`, exactly like the backtest."""
    if weights.empty or since is None or since not in close.index:
        return weights
    rets = close.pct_change().loc[close.index[close.index.get_loc(since) + 1]:today]
    w = weights
    for _, r in rets.iterrows():
        w = drift_weights(w, r)
    return w


def wait_for_opg_window(now_fn=lambda: datetime.now(ET), sleep_fn=time.sleep) -> float:
    """Block until Alpaca accepts opening-auction orders again (19:01 ET) if called inside 09:28-19:00 ET.
    Returns the seconds waited."""
    now = now_fn()
    if not (OPG_CLOSED[0] <= now.time() < OPG_CLOSED[1]):
        return 0.0
    target = now.replace(hour=19, minute=1, second=0, microsecond=0)
    secs = (target - now).total_seconds()
    print(f"Opening-auction orders open at 19:00 ET: waiting {secs / 60:.0f} min before sending", flush=True)
    sleep_fn(secs)
    return secs


def state_path(book: str | None = None) -> Path:
    """One state file per book; the single-book setup keeps the historical data/live_state.json."""
    return STATE_PATH if book is None else STATE_PATH.with_name(f"live_state_{book}.json")


def last_rebalance(path: Path = STATE_PATH) -> pd.Timestamp | None:
    """Date of the last real rebalance recorded in a state file (None before the first)."""
    if not path.exists():
        return None
    v = json.loads(path.read_text()).get("last_rebalance")
    return pd.Timestamp(v) if v else None


def trading_days_since(index: pd.DatetimeIndex, prev: pd.Timestamp, today: pd.Timestamp) -> int:
    """Trading days from `prev` to `today` on the price calendar (prev not on the calendar -> very large)."""
    if prev not in index:
        return 10 ** 6
    return int(index.get_loc(today) - index.get_loc(prev))


def load_state(path: Path = STATE_PATH) -> State:
    if not path.exists():
        return State()
    d = json.loads(path.read_text())
    return State(weights=pd.Series(d["weights"], dtype=float), last_exit={k: pd.Timestamp(v) for k, v in d["last_exit"].items()})


def save_state(s: State, path: Path = STATE_PATH, rebalanced: pd.Timestamp | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    d = {"weights": s.weights.round(6).to_dict(), "last_exit": {k: v.isoformat() for k, v in s.last_exit.items()}}
    prev = last_rebalance(path)
    stamp = rebalanced if rebalanced is not None else prev
    if stamp is not None:
        d["last_rebalance"] = pd.Timestamp(stamp).isoformat()
    write_atomic(path, json.dumps(d, indent=2))


def live_features(cfg: dict, rules, close, volume, raw_close, fund):
    """Features for today's ranking. A ranker that scores each day on its own (no training, no optimizer IC) only
    needs today's row, and every price feature looks back at most ~273 days, so the features are computed on the
    last live.feature_window_days bars (default 400) instead of the whole history: same values on today's row, a
    fraction of the memory (the full 2010+ frame for ranks 201-1500 needed > 10 GB). 0 = whole history."""
    win = int((cfg.get("live") or {}).get("feature_window_days", 400) or 0)
    books = build_books(cfg) or [single_book(cfg)]
    needs_hist = rules.sizing == "optimizer" or any(
        (make_ranker(b.ranker, b.ranker_weights) if b.ranker_weights else make_ranker(b.ranker)).needs_training for b in books)
    if not win or needs_hist or len(close.index) <= win:
        return compute_features(close, volume, raw_close=raw_close, fundamentals=fund)
    cut = close.index[-win]
    sl = lambda df: df.loc[cut:] if df is not None else None
    print(f"Features on the last {win} bars (from {cut.date()})", flush=True)
    # fundamentals panels stay whole: they are keyed by their own (filing) calendar and align_to_prices carries the
    # last value before the window forward; slicing them would drop it
    return compute_features(sl(close), sl(volume), raw_close=sl(raw_close), fundamentals=fund)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="rebalance even if portfolio.rebalance_every_days says to hold today")
    ap.add_argument("--provider", default=None, choices=[None, "yfinance", "tiingo", "norgate"])
    ap.add_argument("--allow-stale", action="store_true", help="trade even if the price data is not the latest session")
    args = ap.parse_args()

    cfg = load_config()
    p, m = cfg["portfolio"], cfg["model"]
    # stop this run (before any order) if the machine is about to run out of RAM; see src/memguard.py
    guard = start_guard(cfg.get("live", {}).get("min_free_gb", 1.0))
    rules = build_rules(cfg)
    cost_model = build_cost_model(cfg)
    bt = BacktestConfig(ranker=m["type"], horizon_days=m["horizon_days"], train_window_days=m["train_window_days"])

    # If auto_tune ran in the last backtest, use the most recent tuned appetite live.
    tune_log = Path("data/tune_log.csv")
    if rules.optimizer and cfg.get("auto_tune", {}).get("enabled") and tune_log.exists():
        last = pd.read_csv(tune_log).iloc[-1]
        rules = replace(rules, optimizer=replace(rules.optimizer, risk_aversion=float(last["risk_aversion"]), tc_multiplier=float(last["tc_multiplier"])))
        print(f"Using tuned settings from {last['date']}: risk_aversion={last['risk_aversion']}, tc_multiplier={last['tc_multiplier']}")

    close, volume, raw_close, membership = load_dataset(cfg, provider=args.provider, refresh=True)
    # keep only names that were ever in the universe (plus anything still held): ~3x less memory, and the
    # same ranking cross-section as the backtests that validated the model
    held = set()
    for bk in (build_books(cfg) or [None]):
        held |= set(load_state(state_path(bk.name if bk else None)).weights.index)
    n_all = close.shape[1]
    close, volume, raw_close, membership = trim_to_universe(close, volume, raw_close, membership, keep=held)
    print(f"Universe trim: {n_all} tickers loaded -> {close.shape[1]} ever-members kept", flush=True)
    gate_membership = membership                                          # exposure gates: full universe
    membership = trade_membership(cfg["data"], raw_close, volume, membership)   # ranking: liquidity band, if set
    today = close.index[-1]

    # Data freshness: never trade on yesterday's prices or on a half-updated cross-section
    now_et = datetime.now(ET)
    sessions = trading_sessions(now_et.date() - timedelta(days=14), now_et.date())
    session_today = sessions is None or now_et.date() in sessions
    if (args.provider or cfg["data"].get("provider")) == "norgate":
        try:
            check_data(raw_close, expected_last_session(now_et, sessions))
        except DataNotCurrent as e:
            if not args.allow_stale:
                raise
            print(f"WARNING (--allow-stale): {e}", flush=True)

    # Rebalance cadence: the backtest trades every Nth trading day and holds in between, so do the same live.
    every = int(p.get("rebalance_every_days", 1))
    first_state = state_path((build_books(cfg) or [None])[0].name if build_books(cfg) else None)
    prev = last_rebalance(first_state)
    # With a daily cadence this still holds when the data has no new bar since the last rebalance (n == 0,
    # e.g. the data vendor is late): trading again on the same close would only churn.
    if prev is not None and not args.force:
        n = trading_days_since(close.index, prev, today)
        if n < every:
            print(f"Not a rebalance day: last rebalance {prev.date()}, {n} trading day(s) ago, cadence every {every}. Holding.")
            stop_guard(guard)
            if not session_today:
                print("Market closed today: no equity row (it would overwrite the last session's).")
                return
            if not args.dry_run:
                from src.broker import make_broker
                from src.monitor import append_equity
                broker = make_broker("alpaca", order_type=cfg.get("live", {}).get("order_type", "market"))
                pos = broker.positions()
                equity = broker.equity()
                append_equity(today, equity, equity - float(pos.sum()), int((pos > 0).sum()))
                print(f"equity ${equity:,.0f} logged; no orders")
            return

    if p.get("sector_mode"):
        # sector lookups only for names that can be bought today (or are held)
        candidates = set(membership.iloc[-1][membership.iloc[-1]].index) if membership is not None else set(close.columns)
        for bk in (build_books(cfg) or [None]):
            candidates |= set(load_state(state_path(bk.name if bk else None)).weights.index)
        sectors = load_sectors(sorted(candidates))
        rules = replace(rules, sectors=sectors)
        print(f"Sector mode '{p['sector_mode']}': {len(set(sectors.values()) - {'Unknown'})} sectors, "
              f"{sum(v == 'Unknown' for v in sectors.values())} names without a sector")

    if p.get("exposure"):
        # market-regime scaling: shrink the invested budget when the universe index says so
        e = float(exposure_series(p["exposure"], close, gate_membership).iloc[-1])
        rules = scale_rules(rules, e)
        print(f"Exposure '{p['exposure']}': {e:.2f} -> invested budget {1 - rules.cash_buffer:.0%}")

    fund = fundamentals_from_config(cfg, close, refresh=True)
    feats = live_features(cfg, rules, close, volume, raw_close, fund)
    labels = forward_excess_return(close, bt.horizon_days)
    vol = realized_vol(close, p["vol_lookback_days"]).loc[today]
    adv_today = dollar_adv(raw_close, volume, 60).loc[today]
    daily_vol = close.pct_change().iloc[-20:].std()
    members_today = membership.iloc[-1] if membership is not None else None

    books = build_books(cfg)
    multi = books is not None
    if not multi:
        books = [single_book(cfg)]
    else:
        print("Books: " + ", ".join(f"{b.name} ({b.ranker}, {b.weight:.0%}, top {b.top_n or rules.top_n})" for b in books))

    # The account as it stands (read-only). Live: the rules start from these actual weights. Dry run: the same, on a
    # paper copy of the account, so the dry run shows exactly the orders a real run would send.
    sleeve_assets = set((p.get("sleeve") or {}).get("assets") or [])
    acct = None
    try:
        from src.broker import AlpacaBroker
        _ab = AlpacaBroker()
        acct = (_ab.positions(), float(_ab.equity()), _ab.position_qty())
    except Exception as e:   # noqa: BLE001
        if not args.dry_run:
            raise
        print(f"Alpaca account not readable ({type(e).__name__}): dry run starts from the saved weights drifted to today")

    book_w, book_states, book_scores, book_prev = {}, {}, {}, {}
    for b in books:
        b_rules = book_rules(rules, b) if multi else rules
        ranker = make_ranker(b.ranker, b.ranker_weights) if b.ranker_weights else make_ranker(b.ranker)
        if ranker.needs_training:
            end = close.index[-1 - bt.horizon_days]
            ranker.fit(feats.loc[close.index[-bt.train_window_days]:end], labels, end_date=end)
        scores = ranker.score(feats.xs(today, level="date"))
        if members_today is not None:
            scores = scores[scores.index.isin(members_today[members_today].index)]
        # Norgate renames a stock that delists (or is about to) to TICKER-YYYYMM; nothing tradeable is left behind it
        dead = scores.index[scores.index.str.contains(r"-\d{6}$", regex=True)]
        if len(dead):
            print(f"Dropping {len(dead)} delisted/renamed name(s) from today's ranking: {', '.join(dead)}")
            scores = scores.drop(dead)

        b_path = state_path(b.name if multi else None)
        state = load_state(b_path)
        if not multi and acct is not None:
            w_now = account_weights(acct[0], acct[1], sleeve_assets)
            print(f"Starting from the account's actual weights: {len(w_now)} names, {w_now.sum():.1%} in stocks")
            state = State(weights=w_now, last_exit=state.last_exit)
        else:   # books share one account: each book's saved weights drift with prices, as in the backtest
            state = State(weights=drifted(state.weights, close, last_rebalance(b_path), today), last_exit=state.last_exit)
        ret_win, ic = None, float("nan")
        if b_rules.sizing == "optimizer":
            ret_win = close.pct_change().iloc[-b_rules.optimizer.cov_lookback:]
            ic = trailing_ic(ranker, feats, labels, close.index, bt.horizon_days)
            print(f"Trailing IC: {ic:.3f}" if ic == ic else "Trailing IC: n/a (using ic_default)")
        w_b, trades, new_state = rebalance(scores, vol, b_rules, state, today, returns_window=ret_win, ic=ic,
                                           adv=adv_today, cost_model=cost_model)
        est_cost = cost_model.trade_cost(trades, adv_today, daily_vol)
        head = f"[{b.name}] " if multi else ""
        print(f"{head}Estimated cost of today's trades: {est_cost * 1e4:.1f} bps of portfolio")
        n_show = int((w_b > 0).sum()) if b_rules.sizing == "optimizer" else b_rules.top_n
        print(f"{head}As of {today.date()} — {n_show} positions chosen:")
        print(scores.sort_values(ascending=False).head(max(n_show, 10)).round(3).to_string())
        print(f"\n{head}Trades (Δ weight):")
        print(trades.round(4).to_string() if not trades.empty else "  none")
        book_w[b.name], book_states[b.name], book_scores[b.name], book_prev[b.name] = w_b, new_state, scores, state.weights

    new_w = combine_weights(book_w)
    if multi:
        print(f"\nCombined: {int((new_w > 0).sum())} names, {new_w.sum():.1%} invested "
              f"({', '.join(f'{k} {v.sum():.1%}' for k, v in book_w.items())})")

    # idle-cash sleeve: whatever the exposure layer left uninvested (above the base buffer) goes to ETFs
    targets, prices_today = new_w, raw_close.loc[today]
    if p.get("sleeve"):
        from src.config import build_sleeve
        from src.sleeve import live_sleeve_targets, sleeve_prices
        sl = build_sleeve(cfg)
        sl_px = sleeve_prices(sl.assets, close.index)
        sleeve_w = live_sleeve_targets(new_w, p["cash_buffer"], sl, sl_px)
        targets = pd.concat([new_w, sleeve_w[sleeve_w > 0]])
        print(f"Sleeve ({sl.rule} {','.join(sl.assets)}): stocks {new_w.sum():.1%}, sleeve {sleeve_w.sum():.1%}, "
              f"cash {1 - targets.sum():.1%} -> " + ", ".join(f"{k} {v:.1%}" for k, v in sleeve_w.items()))
        if args.dry_run:   # the paper broker needs a price for every target
            from src.exposure import EXT_LOADER
            raw_etf = EXT_LOADER(list(sl.assets)).ffill().iloc[-1]
            prices_today = pd.concat([prices_today, raw_etf.reindex(sl.assets)])

    # names the rules left untouched (inside the no-trade band) are not traded at all
    prev_all = combine_weights(book_prev) if multi else book_prev[books[0].name]
    skip = {t for t in new_w.index if t in prev_all.index and abs(float(new_w[t]) - float(prev_all[t])) < 1e-12}
    print(f"Held inside the no-trade band (not traded): {len(skip)} names")

    from src.broker import PaperBroker, make_broker
    from src.monitor import append_equity, write_ranking
    stop_guard(guard)   # the heavy work is done; never cut a run off while it is sending orders
    order_type = cfg.get("live", {}).get("order_type", "market")
    if args.dry_run:
        import tempfile
        broker = PaperBroker(Path(tempfile.gettempdir()) / "stocktrader_dryrun_account.json")
        broker.acct = {"cash": 100_000.0, "positions": {}}
        if acct is not None:   # a paper copy of the real account, priced at today's close
            pos, eq, qty = acct
            broker.acct = {"cash": eq - float(pos.sum()),
                           "positions": {t: {"qty": float(qty[t]), "price": float(pos[t]) / float(qty[t])}
                                         for t in pos.index if float(qty.get(t, 0.0)) != 0.0}}
        broker.mark(prices_today)
    else:
        broker = make_broker("alpaca", order_type=order_type)
        if order_type == "opg":
            del close, volume, raw_close, feats, labels, membership, gate_membership
            gc.collect()
            wait_for_opg_window()
    orders = broker.submit_targets(targets, prices_today, skip=skip)
    equity = broker.equity()
    cash = equity - float(broker.positions().sum())
    print(f"\n{len(orders)} orders  |  equity ${equity:,.0f}")
    if args.dry_run:
        print("dry run: live state, equity log and orders.log left untouched")
        return
    failed = sorted({o["ticker"] for o in orders if o.get("error")})
    if failed:
        log_error(f"{len(failed)} order(s) rejected on {today.date()}: {', '.join(failed)}")
        for b in books:   # an exit that was rejected did not happen: no re-entry cooldown for it
            st = book_states[b.name]
            for t in failed:
                if st.last_exit.get(t) == today:
                    st.last_exit.pop(t)
    for b in books:
        save_state(book_states[b.name], state_path(b.name if multi else None), rebalanced=today)
    append_equity(today, equity, cash, int((new_w > 0).sum()))
    for b in books:   # one ranking file per book (latest_ranking.csv for the single-book setup)
        write_ranking(book_scores[b.name], book_w[b.name], book_prev[b.name], b.top_n or rules.top_n,
                      data_dir=Path("data") / "books" / b.name if multi else Path("data"))

    log = Path("data/orders.log")
    with open(log, "a") as f:
        f.write(json.dumps({"date": str(date.today()), "orders": orders}) + "\n")


if __name__ == "__main__":
    try:
        main()
    except DataNotCurrent as e:
        log_error(f"no trading: {e}")
        sys.exit(3)
    except Exception as e:   # noqa: BLE001 - recorded for the daily check, then the job fails visibly
        log_error(f"run failed: {type(e).__name__}: {str(e)[:300]}")
        raise
