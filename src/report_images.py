"""The image for the daily Discord report: one dashboard sized for a phone. Dark theme to match Discord. Pure drawing:
takes the same ctx as src/discord_report.py. Returns by period are in the embed text and the full holdings list is on
the web page (src/report_site.py), so neither is repeated here.

Colours (dataviz reference palette, dark steps): gains / buys = blue, losses / sells = red (diverging pair, every
value also carries its sign); SPY = orange; the money split uses violet / aqua / yellow plus gray for cash.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from src.discord_report import SLEEVE, money, pct  # noqa: E402

BG = "#1a1a19"
INK, INK2, MUTED, GRID = "#f0efec", "#c3c2b7", "#8a897f", "#383835"
POS, NEG, SPY = "#3987e5", "#e66767", "#d95926"
SPLIT = {"Stocks": "#9085e9", "IEF": "#199e70", "GLD": "#c98500", "Cash": "#6b6a64"}
FONT = "Segoe UI"


def _style():
    plt.rcParams.update({"font.family": [FONT, "DejaVu Sans"], "font.size": 15, "text.color": INK, "axes.labelcolor": INK2,
                         "xtick.color": MUTED, "ytick.color": INK2, "axes.edgecolor": GRID, "figure.facecolor": BG,
                         "axes.facecolor": BG, "savefig.facecolor": BG})


def _clean(ax):
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return buf.getvalue()


def _k(v: float) -> str:
    return f"${v / 1000:,.1f}k" if abs(v) >= 1000 else f"${v:,.0f}"


def _bars(ax, labels, values, texts, colors, fs=14):
    """Horizontal bars from a zero baseline, rounded ends, a value label just past each bar end."""
    y = list(range(len(labels)))[::-1]
    span = max([abs(v) for v in values] + [1e-9])
    for yi, v, c in zip(y, values, colors):
        w = v if abs(v) > span * 0.01 else (span * 0.01 if v >= 0 else -span * 0.01)
        ax.add_patch(FancyBboxPatch((min(0, w), yi - 0.3), abs(w), 0.6, boxstyle="round,pad=0,rounding_size=0.08",
                                    linewidth=0, facecolor=c, mutation_aspect=1 / max(span, 1e-9) * 2))
    for yi, v, t in zip(y, values, texts):
        ax.text(v + (span * 0.03 if v >= 0 else -span * 0.03), yi, t, va="center", ha="left" if v >= 0 else "right",
                color=INK, fontsize=fs)
    ax.set_yticks(y, labels, fontsize=fs)
    ax.axvline(0, color=MUTED, linewidth=1)
    lo, hi = min(values + [0]), max(values + [0])
    pad = span * 1.1
    ax.set_xlim(lo - (pad if lo < 0 else span * 0.05), hi + (pad if hi > 0 else span * 0.05))
    ax.set_ylim(-0.6, len(labels) - 0.4)
    ax.set_xticks([])


def dashboard(ctx: dict) -> bytes:
    """Value and today's change, account vs SPY since the start, where the money is, today's biggest movers among the
    holdings, and today's biggest trades."""
    _style()
    t = ctx["today"]
    eq = ctx["equity"]
    fig = plt.figure(figsize=(9, 12.6))
    gs = fig.add_gridspec(5, 2, height_ratios=[0.85, 2.6, 0.75, 2.2, 2.6], hspace=0.62, wspace=0.42,
                          left=0.14, right=0.95, top=0.97, bottom=0.05)

    # header
    ax = fig.add_subplot(gs[0, :]); ax.axis("off")
    day = next((r for r in ctx["returns"] if r["label"] == "Day"), None)
    ax.text(0, 1.05, f"{t.strftime('%A, %B %d').replace(' 0', ' ')}  ·  {'paper' if ctx['paper'] else 'LIVE'} account",
            fontsize=15, color=INK2, va="top", transform=ax.transAxes)
    ax.text(0, 0.30, money(eq), fontsize=38, fontweight="bold", color=INK, va="center", transform=ax.transAxes)
    if day:
        up = day["pct"] >= 0
        ax.text(1.0, 0.30, f"{'▲' if up else '▼'} {pct(day['pct'])} today\n{money(day['dollars'], True)}", fontsize=19,
                color=POS if up else NEG, va="center", ha="right", transform=ax.transAxes, linespacing=1.3)

    # account vs SPY, % change since the start (one axis: both start at 0%)
    ax = fig.add_subplot(gs[1, :]); _clean(ax)
    curve = ctx.get("curve") or []
    spy = dict(ctx.get("spy") or [])
    if len(curve) >= 2:
        xs = [d for d, _ in curve]
        acct = [(v / curve[0][1] - 1) * 100 for _, v in curve]
        s0 = next((spy[d] for d in xs if d in spy), None)
        sp = [(x, (spy[x] / s0 - 1) * 100) for x in xs if s0 and x in spy]
        ax.axhline(0, color=MUTED, linewidth=1)
        if len(sp) > 1:
            ax.plot([x for x, _ in sp], [v for _, v in sp], color=SPY, linewidth=2)
            ax.text(sp[-1][0], sp[-1][1], f"  SPY {sp[-1][1]:+.1f}%", color=INK2, fontsize=14, va="center")
        ax.plot(xs, acct, color=POS, linewidth=2.4)
        ax.scatter([xs[-1]], [acct[-1]], s=50, color=POS, edgecolor=BG, linewidth=2, zorder=3)
        ax.text(xs[-1], acct[-1], f"  Account {acct[-1]:+.1f}%", color=INK, fontsize=14, va="center", fontweight="bold")
        ax.grid(axis="y", color=GRID, linewidth=0.8); ax.set_axisbelow(True)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:+.0f}%" if abs(v) > 1e-9 else "0%"))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=5))
        ax.set_xlim(xs[0], xs[-1] + (xs[-1] - xs[0]) * 0.30)
        allv = acct + [v for _, v in sp]
        lo, hi = min(allv + [0]), max(allv + [0])
        ax.set_ylim(lo - (hi - lo) * 0.12 - 0.05, hi + (hi - lo) * 0.12 + 0.05)   # room so labels never touch the dates
        ax.tick_params(axis="x", pad=8)
    ax.set_title("Account vs the S&P 500 since the start", loc="left", color=INK2, fontsize=16, pad=10)

    # where the money is
    ax = fig.add_subplot(gs[2, :]); ax.axis("off")
    pos = ctx["positions"]
    parts = {"Stocks": sum(p["value"] for p in pos if p["symbol"] not in SLEEVE),
             "IEF": sum(p["value"] for p in pos if p["symbol"] == "IEF"),
             "GLD": sum(p["value"] for p in pos if p["symbol"] == "GLD"),
             "Cash": max(ctx["cash"], 0.0)}
    total = sum(parts.values()) or 1.0
    x = 0.0
    for k, v in parts.items():
        w = v / total
        if w <= 0:
            continue
        ax.add_patch(FancyBboxPatch((x + 0.002, 0.0), max(w - 0.004, 0.001), 0.55, boxstyle="round,pad=0,rounding_size=0.012",
                                    facecolor=SPLIT[k], linewidth=0, transform=ax.transAxes))
        if w >= 0.08:
            ax.text(x + w / 2, 0.27, f"{k} {w:.0%}", ha="center", va="center", color="#0b0b0b", fontsize=15,
                    fontweight="bold", transform=ax.transAxes)
        x += w
    small = [f"{k} {v / total:.0%}" for k, v in parts.items() if 0 < v / total < 0.08]
    ax.text(0, 1.05, "Where the money is" + (f"   ({', '.join(small)})" if small else ""), color=INK2, fontsize=16,
            va="bottom", transform=ax.transAxes)

    # biggest movers today among the holdings, by dollars gained or lost
    ax = fig.add_subplot(gs[3, :]); _clean(ax)
    movers = sorted([p for p in pos if abs(p["day_pl"]) >= 0.01], key=lambda p: p["day_pl"])
    pick = movers[:4] + [p for p in movers[-4:] if p not in movers[:4]]
    pick = sorted(pick, key=lambda p: -p["day_pl"])
    if pick:
        _bars(ax, [p["symbol"] for p in pick], [p["day_pl"] for p in pick],
              [f"{money(p['day_pl'], True)}  ({pct(p['day_pct'])})" for p in pick],
              [POS if p["day_pl"] >= 0 else NEG for p in pick])
    else:
        ax.axis("off"); ax.text(0, 0.5, "No price changes yet today", color=MUTED, transform=ax.transAxes)
    ax.set_title("Biggest movers today", loc="left", color=INK2, fontsize=16, pad=10)

    # today's biggest trades
    tr = ctx["trades"]
    buys = sorted(tr["new"] + tr["added"], key=lambda x: -x[1])
    sells = sorted(tr["trimmed"] + tr["exited"], key=lambda x: -x[1])
    new, out = {s for s, _ in tr["new"]}, {s for s, _ in tr["exited"]}
    for col, (items, title, color) in enumerate(((buys, "Bought", POS), (sells, "Sold", NEG))):
        ax = fig.add_subplot(gs[4, col]); _clean(ax)
        top = items[:6]
        if top:
            labels = [s + (" ★" if s in new else " ✕" if s in out else "") for s, _ in top]
            _bars(ax, labels, [v for _, v in top], [_k(v) for _, v in top], [color] * len(top))
        else:
            ax.axis("off"); ax.text(0, 0.5, "none", color=MUTED, transform=ax.transAxes)
        ax.set_title(f"{title} today: {len(items)}", loc="left", color=INK2, fontsize=16, pad=10)
    fig.text(0.14, 0.012, "★ new position    ✕ sold out    biggest 6 shown; everything is on the Full report page",
             color=MUTED, fontsize=12)
    return _png(fig)
