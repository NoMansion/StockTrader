"""Two (or more) books sharing one account.

A book is a ranker with its own share of the invested budget and its own rebalance state. Books
run independently (each sees the whole universe and the same exposure signal) and their target
weights add up; a name both books hold simply gets both weights. This is how the sweep found the
earnings book should be combined with momentum: blending the earnings score INTO the momentum
rank lost Sharpe, a 50/50 split of capital between two books did not.

config.yaml:
    portfolio:
      books:                       # null = one book from model.type (default)
        - {name: momentum, ranker: consistency_heavy, weight: 0.7}
        - {name: earnings, ranker: earnings, weight: 0.3, top_n: 40}

Book weights must sum to 1. Per-book rules: top_n (default portfolio.top_n) and
cash_buffer' = 1 - weight * (1 - cash_buffer), so the books together invest the usual budget.
The sleeve / cash yield apply once, to the combined book, not per book.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from .portfolio import Rules


@dataclass(frozen=True)
class Book:
    name: str
    ranker: str
    weight: float
    top_n: int | None = None
    ranker_weights: dict | None = None

    def __post_init__(self):
        if not (0 < self.weight <= 1):
            raise ValueError(f"book {self.name!r}: weight must be in (0, 1], got {self.weight}")


def build_books(cfg: dict) -> list[Book] | None:
    """Books from portfolio.books, or None when the config has a single implicit book."""
    spec = cfg["portfolio"].get("books")
    if not spec:
        return None
    books = [Book(name=str(b["name"]), ranker=str(b["ranker"]), weight=float(b["weight"]),
                  top_n=b.get("top_n"), ranker_weights=b.get("weights")) for b in spec]
    names = [b.name for b in books]
    if len(set(names)) != len(names):
        raise ValueError(f"book names must be unique: {names}")
    total = sum(b.weight for b in books)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"book weights must sum to 1, got {total:.4f}")
    return books


def single_book(cfg: dict) -> Book:
    """The implicit book when portfolio.books is not set."""
    m = cfg["model"]
    return Book(name="main", ranker=m["type"], weight=1.0, ranker_weights=m.get("weights"))


def book_rules(rules: Rules, book: Book) -> Rules:
    """Rules for one book: its top_n and its share of the invested budget."""
    return replace(rules, top_n=book.top_n or rules.top_n, cash_buffer=1.0 - book.weight * (1.0 - rules.cash_buffer))


def combine_weights(per_book: dict[str, pd.Series]) -> pd.Series:
    """Add the books' target weights (a name in several books gets the sum)."""
    if not per_book:
        return pd.Series(dtype=float)
    return pd.concat(per_book.values()).groupby(level=0).sum().sort_values(ascending=False)


def run_books(close, volume, rules: Rules, cfg, books: list[Book], **kw):
    """Backtest each book with its own rules/ranker and combine them into one BacktestResult.
    `cfg` is the BacktestConfig; its sleeve / cash_yield apply to the combined result."""
    from .backtest import BacktestResult, run_backtest

    results = {}
    for b in books:
        bcfg = replace(cfg, ranker=b.ranker, ranker_weights=b.ranker_weights, sleeve=None, cash_yield=False)
        results[b.name] = run_backtest(close, volume, book_rules(rules, b), bcfg, **kw)
    result = combine_results(results)
    if cfg.sleeve is not None or cfg.cash_yield:
        from .sleeve import apply_cash_yield, apply_sleeve
        if cfg.sleeve is not None:
            result = apply_sleeve(result, rules.cash_buffer, cfg.sleeve)
        if cfg.cash_yield:
            result = apply_cash_yield(result)
    return result


def combine_results(results: dict):
    """Sum the books' daily returns, costs, turnover and weights (each is already on a whole-account
    basis because every book holds its unused share as cash)."""
    from .backtest import BacktestResult

    names = list(results)
    first = results[names[0]].daily
    idx = first.index
    for r in results.values():
        idx = idx.union(r.daily.index)
    daily = pd.DataFrame(index=idx)
    for col in ("ret", "turnover", "cost", "n_pos"):
        daily[col] = sum(r.daily[col].reindex(idx).fillna(0.0) for r in results.values())
    daily["bench_ret"] = first["bench_ret"].reindex(idx)
    daily["ic"] = pd.concat([r.daily["ic"].reindex(idx) for r in results.values()], axis=1).mean(axis=1)
    for n in names:
        daily[f"ret_{n}"] = results[n].daily["ret"].reindex(idx)
    cols = pd.Index([])
    for r in results.values():
        cols = cols.union(r.weights.columns)
    weights = sum(r.weights.reindex(index=idx, columns=cols).fillna(0.0) for r in results.values())
    trades = pd.concat([r.trades.assign(book=n) for n, r in results.items()], ignore_index=True) if any(len(r.trades) for r in results.values()) else pd.DataFrame(columns=["date", "ticker", "delta_w", "book"])
    tune = pd.concat([r.tune_log.assign(book=n) for n, r in results.items() if not r.tune_log.empty], ignore_index=True) if any(not r.tune_log.empty for r in results.values()) else pd.DataFrame()
    return BacktestResult(daily=daily, weights=weights, trades=trades, tune_log=tune)
