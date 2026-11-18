"""Daily Discord report: pure functions (no network). scripts/discord_report.py does the I/O.

What the report shows
    one Discord embed: account value, the change over day / week / month / year / YTD / all time (dividends
    included, deposits and withdrawals excluded), how many names were bought and sold today and how many orders
    wait for the next open; one dashboard image (src/report_images.py) and a link to the full page
    (src/report_site.py).

Deposits and withdrawals: returns are time-weighted (growth_index), so money put in or taken out never shows as a gain
or loss; the $ changes subtract the net amount put in. Money that arrives before the first trade is the starting
value.

Dividends: a live account is paid them as cash (DIV activities), so they are already in its equity. Alpaca paper
accounts have not received any so far (no DIV activity since the account opened 2026-11-06), so for paper the report
estimates them from the dividend calendar: shares held at the close before each ex-date x the declared rate, and adds
the running total to equity before computing the percent changes. If the account ever shows a DIV activity the report
uses the real ones instead.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import date, timedelta

SLEEVE = ("IEF", "GLD", "TLT", "SHY")
DUST_WEIGHT = 0.001            # holdings under 0.1% of the account are leftover fractional shares; summarised in one line
MSG_LIMIT = 1990               # Discord allows 2,000 characters per message


# ---------------------------------------------------------------- returns
def _ref_value(series: list[tuple[date, float]], cutoff: date) -> tuple[date, float] | None:
    """Last (date, value) on or before `cutoff`, or None if the series starts later."""
    dates = [d for d, _ in series]
    i = bisect.bisect_right(dates, cutoff) - 1
    return series[i] if i >= 0 else None


def _months_back(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError(d)


def growth_index(series: list[tuple[date, float]], flows: dict[date, float] | None = None) -> list[tuple[date, float]]:
    """The account value with deposits and withdrawals taken out: starts at the first value and then moves only by
    each day's return, r = (value - net deposits that day) / previous value - 1. Deposits count at the end of their
    day, so a deposit the history books one day late still nets out over the two days."""
    flows = flows or {}
    series = [(d, v) for d, v in series if v > 0]
    if not series:
        return []
    out = [series[0]]
    for (d0, v0), (d1, v1) in zip(series, series[1:]):
        out.append((d1, out[-1][1] * (v1 - flows.get(d1, 0.0)) / v0))
    return out


def period_returns(series: list[tuple[date, float]], today: date, flows: dict[date, float] | None = None) -> list[dict]:
    """series: (date, account value) sorted, last item = today's. flows: net deposits (+) / withdrawals (-) by date,
    already excluding the initial funding. Each row: label, pct (time-weighted: deposits are not gains), dollars (the
    change in value minus the money put in), since (the start date used when the account is younger than the
    window, else None)."""
    flows = flows or {}
    series = [(d, v) for d, v in series if v > 0]
    if len(series) < 2:
        return []
    idx = dict(growth_index(series, flows))
    first, (t_now, v_now) = series[0], series[-1]
    prev = series[-2]
    windows = [("Day", prev, False),
               ("Week", _ref_value(series, today - timedelta(days=7)), True),
               ("Month", _ref_value(series, _months_back(today, 1)), True),
               ("Year", _ref_value(series, _months_back(today, 12)), True),
               ("YTD", _ref_value(series, date(today.year - 1, 12, 31)), True),
               ("All time", first, False)]
    rows = []
    for label, ref, can_be_short in windows:
        short = ref is None
        d0, v0 = first if short else ref
        added = sum(f for d, f in flows.items() if d0 < d <= t_now)
        rows.append({"label": label, "pct": idx[t_now] / idx[d0] - 1, "dollars": v_now - v0 - added,
                     "since": d0 if (short and can_be_short) else None})
    return rows


FLOW_TYPES = ("CSD", "CSW", "JNLC", "JNLS", "ACATC", "ACATS", "TRANS")   # money or shares moved in or out (not FEE/DIV/INT)


def external_flows(by_type: dict[str, list[float]], dates: list[date], first_trade: date | None) -> dict[date, float]:
    """Net deposits by date from the portfolio history's `cashflow` arrays (aligned with `dates`). Anything up to the
    first trade is the initial funding, already in the starting value, so it is left out (the paper account's
    $100,000 is booked a day after the history already shows it)."""
    out: dict[date, float] = defaultdict(float)
    for typ, arr in by_type.items():
        if typ not in FLOW_TYPES:
            continue
        for d, x in zip(dates, arr):
            if x and (first_trade is None or d > first_trade):
                out[d] += float(x)
    return {d: x for d, x in out.items() if abs(x) > 1e-9}


# ---------------------------------------------------------------- fills
def signed(fill: dict) -> float:
    q = float(fill["qty"])
    return q if fill["side"] == "buy" else -q


def holdings_before(fills: list[dict], day: date) -> dict[str, float]:
    """Shares held at the close before `day`, from the fill history (fill['date'] = ET trade date)."""
    pos: dict[str, float] = defaultdict(float)
    for f in fills:
        if f["date"] < day:
            pos[f["symbol"]] += signed(f)
    return {s: q for s, q in pos.items() if q > 1e-9}


def trades_today(today_fills: list[dict], qty_now: dict[str, float], price_now: dict[str, float]) -> dict[str, list]:
    """Group today's fills by symbol: new (no shares before today), added, trimmed, exited (none left)."""
    by = defaultdict(lambda: {"buy_q": 0.0, "buy_v": 0.0, "sell_q": 0.0, "sell_v": 0.0})
    for f in today_fills:
        q, p = float(f["qty"]), float(f["price"])
        k = "buy" if f["side"] == "buy" else "sell"
        by[f["symbol"]][f"{k}_q"] += q
        by[f["symbol"]][f"{k}_v"] += q * p
    out = {"new": [], "added": [], "trimmed": [], "exited": []}
    for sym, a in by.items():
        net_q = a["buy_q"] - a["sell_q"]
        now = qty_now.get(sym, 0.0)
        before = now - net_q
        val = a["buy_v"] - a["sell_v"]
        if net_q > 0:
            kind = "new" if before < 1e-6 else "added"
        else:
            kind = "exited" if now < 1e-6 or now * price_now.get(sym, 0.0) < 1.0 else "trimmed"
        out[kind].append((sym, abs(val)))
    for k in out:
        out[k].sort(key=lambda x: -x[1])
    return out


def daily_history(curve: list[tuple[date, float]], spy: list[tuple[date, float]], fills: list[dict]) -> list[dict]:
    """One row per day: account and SPY change that day, account change since the start, and how many names had a
    net buy / net sell that day."""
    spy_d = dict(spy)
    net: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for f in fills:
        net[f["date"]][f["symbol"]] += signed(f)
    out = []
    for i, (d, v) in enumerate(curve):
        if i == 0:
            continue
        pd_, pv = curve[i - 1]
        s0, s1 = spy_d.get(pd_), spy_d.get(d)
        n = net.get(d, {})
        out.append({"d": d.isoformat(), "day": v / pv - 1, "cum": v / curve[0][1] - 1,
                    "spy": (s1 / s0 - 1) if (s0 and s1) else None,
                    "buys": sum(1 for q in n.values() if q > 1e-9), "sells": sum(1 for q in n.values() if q < -1e-9)})
    return out


# ---------------------------------------------------------------- dividends
def estimated_dividends(fills: list[dict], divs: list[dict], today: date) -> list[dict]:
    """divs: {symbol, ex_date (date), rate, payable_date}. Shares held at the close before the ex-date x rate."""
    out = []
    by_sym = defaultdict(list)
    for f in fills:
        by_sym[f["symbol"]].append(f)
    for d in divs:
        if d["ex_date"] > today or d["symbol"] not in by_sym:
            continue
        q = sum(signed(f) for f in by_sym[d["symbol"]] if f["date"] < d["ex_date"])
        if q > 1e-9:
            out.append({**d, "shares": q, "amount": q * float(d["rate"])})
    return sorted(out, key=lambda x: x["ex_date"])


def cumulative_by_date(items: list[dict], key_date: str, dates: list[date]) -> list[float]:
    """Running total of item['amount'] counted on item[key_date], evaluated at each of `dates`."""
    pts = sorted((it[key_date], it["amount"]) for it in items)
    out, run, j = [], 0.0, 0
    for d in dates:
        while j < len(pts) and pts[j][0] <= d:
            run += pts[j][1]
            j += 1
        out.append(run)
    return out


def dividends_in_window(items: list[dict], key_date: str, start_excl: date | None, end: date) -> float:
    return sum(it["amount"] for it in items if (start_excl is None or it[key_date] > start_excl) and it[key_date] <= end)


# ---------------------------------------------------------------- formatting
def money(x: float, sign: bool = False) -> str:
    s = f"{abs(x):,.2f}"
    if sign:
        return ("+$" if x >= 0 else "-$") + s
    return ("-$" if x < 0 else "$") + s


def pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


POS_COLOR, NEG_COLOR = 0x3987E5, 0xE66767     # embed side stripe: blue on an up day, red on a down day


def _short(d: date) -> str:
    return d.strftime("%b %d").replace(" 0", " ")


def embed(ctx: dict, site_url: str | None = None, image: str | None = None) -> dict:
    """The Discord message as one embed: account value and today's change up top, one field per period (% and $),
    trade counts, queued orders, the dashboard image and a link to the full page. ctx keys: today, paper, equity,
    returns, div_mode ('estimated'|'actual'), div_total, trades, queued (or None)."""
    rows = {r["label"]: r for r in ctx["returns"]}
    day = rows.get("Day")
    up = day is None or day["pct"] >= 0
    arrow = "▲" if up else "▼"
    desc = [f"## {money(ctx['equity'])}"]
    if day:
        desc.append(f"{arrow} **{pct(day['pct'])}** today  ({money(day['dollars'], True)})")
    tr = ctx["trades"]
    n_buy, n_sell = len(tr["new"]) + len(tr["added"]), len(tr["trimmed"]) + len(tr["exited"])
    fields = []
    for lab in ("Week", "Month", "Year", "YTD", "All time"):
        r = rows.get(lab)
        if r:
            v = f"**{pct(r['pct'])}**\n{money(r['dollars'], True)}"
            if r["since"]:
                v += f"\n-# since {_short(r['since'])}"
            fields.append({"name": lab, "value": v, "inline": True})
    if len(fields) % 3 == 2:      # keep the grid even on desktop (3 per row)
        fields.append({"name": "​", "value": "​", "inline": True})
    trades = (f"Bought **{n_buy}** ({len(tr['new'])} new)\nSold **{n_sell}** ({len(tr['exited'])} sold out)"
              if n_buy + n_sell else "No trades")
    fields.append({"name": "Today's trades", "value": trades, "inline": True})
    q = ctx.get("queued")
    if q is not None:
        fields.append({"name": "Next open", "value": (f"**{q['buys']}** buys\n**{q['sells']}** sells" if q["buys"] + q["sells"]
                                                      else "No orders queued\n(check the daily job)"), "inline": True})
    foot = ["Paper account" if ctx["paper"] else "LIVE account"]
    if ctx["div_mode"] == "estimated" and ctx["div_total"] > 0:
        foot.append(f"includes {money(ctx['div_total'])} estimated dividends")
    net_in = sum((ctx.get("flows") or {}).values())
    if abs(net_in) >= 0.01:
        foot.append(f"{money(net_in)} net {'deposited' if net_in > 0 else 'withdrawn'} since the start, not counted as gain")
    e = {"title": f"StockTrader  ·  {ctx['today'].strftime('%a %b %d').replace(' 0', ' ')}",
         "description": "\n".join(desc), "color": POS_COLOR if up else NEG_COLOR, "fields": fields,
         "footer": {"text": "  ·  ".join(foot)}}
    if site_url:
        e["url"] = site_url
    if image:
        e["image"] = {"url": f"attachment://{image}"}
    return e
