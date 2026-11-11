"""GICS sector lookup (level 1, e.g. "Information Technology") via Norgate,
cached to JSON so the daily job only queries new tickers.

Used by the sector modes in portfolio.select_top. For the momentum rankers the
Nov 2026 sweep found that forcing an equal number of names per sector ("equal")
raised holdout Sharpe from ~0.67 to ~0.74 and cut max drawdown, while sector caps
did nothing. For the SUE + FCF-yield ranker it is the other way round: a 20-30%
cap ("cap") beat both the equal split and no sector rule.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CACHE = Path("data/sectors.json")


def load_sectors(tickers, cache_path: Path | str = DEFAULT_CACHE, lookup=None) -> dict[str, str]:
    """ticker -> sector name ("Unknown" when Norgate has none). `lookup` is a
    callable(ticker) -> str | None, defaulting to Norgate's GICS level-1 name."""
    cache_path = Path(cache_path)
    try:
        sec = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        sec = {}
    missing = [t for t in tickers if t not in sec]
    if missing:
        if lookup is None:
            lookup = _norgate_lookup
        for t in missing:
            try:
                sec[t] = lookup(t) or "Unknown"
            except Exception:
                sec[t] = "Unknown"
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(sec, indent=0, sort_keys=True))
        except OSError:
            pass
    return {t: sec.get(t, "Unknown") for t in tickers}


def _norgate_lookup(ticker: str):
    import norgatedata  # Windows-only; lazy so the rest of the package imports anywhere
    return norgatedata.classification_at_level(ticker, "GICS", "Name", 1)
