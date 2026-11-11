"""The daily job: pull latest bars, score, apply rules, send orders.

Run after the close (config: live.schedule_local_time). Orders are market,
day-in-force, so they fill at the next open.

    python scripts/run_daily.py --dry-run          # PaperBroker, no API calls
    python scripts/run_daily.py                    # Alpaca paper (keys in .env)

State (last weights, exit dates) persists in data/live_state.json.
"""
import argparse
import json
from datetime import date
from pathlib import Path

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
from src.portfolio import State, rebalance
from src.ranking import make_ranker, trailing_ic
from src.sectors import load_sectors
from src.universe import apply_membership, trade_membership, trim_to_universe

STATE_PATH = Path("data/live_state.json")


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
    path.write_text(json.dumps(d, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="rebalance even if portfolio.rebalance_every_days says to hold today")
    ap.add_argument("--provider", default=None, choices=[None, "yfinance", "tiingo", "norgate"])
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

    feats = compute_features(close, volume, raw_close=raw_close, fundamentals=fundamentals_from_config(cfg, close, refresh=True))
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

        state = load_state(state_path(b.name if multi else None))
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

    from src.broker import make_broker
    from src.monitor import append_equity, write_ranking
    stop_guard(guard)   # the heavy work is done; never cut a run off while it is sending orders
    broker = make_broker("paper" if args.dry_run else "alpaca", order_type=cfg.get("live", {}).get("order_type", "market"))
    if args.dry_run:
        broker.mark(prices_today)
    orders = broker.submit_targets(targets, prices_today)
    equity = broker.equity()
    cash = equity - float(broker.positions().sum())
    print(f"\n{len(orders)} orders  |  equity ${equity:,.0f}")
    if args.dry_run:
        print("dry run: live state, equity log and orders.log left untouched")
        return
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
    main()
