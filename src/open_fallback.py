"""Opening-auction fallback: after the open, resend every auction (OPG) order from last night's batch that did not
fill (expired / canceled / rejected, or only partly filled) as a regular market order, so the account reaches its
targets every day. With live.order_type "opg" the auction gives the official opening price whenever it works; the
fallback costs a few minutes and the early-session spread when it does not.

Pure planning only (no broker calls) so it can be tested; scripts/open_fallback.py does the I/O.
"""
from __future__ import annotations

import json
from pathlib import Path

UNFILLED_END = {"expired", "canceled", "cancelled", "rejected", "done_for_day"}
WHOLE_DONE = {"filled"}


def last_batch(log_path: Path = Path("data/orders.log")) -> dict | None:
    """The last run_daily batch in orders.log (fallback lines are skipped)."""
    if not log_path.exists():
        return None
    for line in reversed(log_path.read_text().splitlines()):
        if line.strip():
            rec = json.loads(line)
            if not rec.get("fallback"):
                return rec
    return None


def plan_resends(batch_orders: list[dict], status: dict[str, dict], held_qty: dict[str, float],
                 already: set[str] | None = None) -> tuple[list[dict], list[str]]:
    """Which auction orders to resend, and how many shares.

    batch_orders  the orders.log records of last night's batch ({"ticker", "side", "tif", "qty", "id"})
    status        Alpaca's view of each order id: {"status": str, "qty": float, "filled_qty": float}
    held_qty      current position quantity per ticker (a sell is capped at what is held: never short)
    already       original order ids a previous fallback run today already resent
    Returns (resends sells first then buys: {"ticker", "side", "qty", "orig_id"}, notes)."""
    already = already or set()
    out, notes = [], []
    for o in batch_orders:
        if str(o.get("tif", "")).lower() != "opg":
            continue
        oid = o.get("id")
        if not oid:
            notes.append(f"{o['ticker']}: auction order was never accepted ({o.get('error', 'no id')[:80]}); not resent")
            continue
        if oid in already:
            continue
        s = status.get(oid)
        if s is None:
            notes.append(f"{o['ticker']}: order {oid[:8]} not found at the broker; not resent")
            continue
        st = str(s["status"]).lower()
        if st in WHOLE_DONE:
            continue
        if st not in UNFILLED_END:
            notes.append(f"{o['ticker']}: auction order still '{st}'; not resent")
            continue
        remaining = float(s.get("qty") or o.get("qty") or 0) - float(s.get("filled_qty") or 0)
        if o["side"] == "sell":
            remaining = min(remaining, float(held_qty.get(o["ticker"], 0.0)))
        remaining = int(remaining)          # auction legs are whole shares
        if remaining <= 0:
            continue
        out.append({"ticker": o["ticker"], "side": o["side"], "qty": remaining, "orig_id": oid, "orig_status": st})
    out.sort(key=lambda r: (r["side"] != "sell", r["ticker"]))
    return out, notes
