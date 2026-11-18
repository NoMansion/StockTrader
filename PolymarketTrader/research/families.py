"""Strategy families for the Kalshi backtests. Each family is a generator of rules:

    (family, rule name, mask over panel rows, side, entry)

A mask may use only columns known at the end of the bar (see research/panel.py). Rules are deliberately simple
and many: the point of a sweep is to see which shapes survive out of sample, not to tune one of them.
"""
from __future__ import annotations

import itertools
import re

import numpy as np

from backtest import Panel

PRICE = [(0.00, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.35), (0.35, 0.50), (0.50, 0.65), (0.65, 0.80),
         (0.80, 0.90), (0.90, 0.95), (0.95, 1.00)]
DTE = [(0, 1), (1, 3), (3, 7), (7, 14), (14, 30), (30, 90), (90, 10000)]
SIDES = ("yes", "no")
ENTRIES = ("tk", "mk")


class Features:
    """Arrays the families share, computed once."""

    def __init__(self, p: Panel):
        d = p.df
        self.p = p
        self.q = d["quoted"].to_numpy(bool)
        self.mid = np.nan_to_num(d["mid"].to_numpy("float32"), nan=-1.0)
        self.spread = np.nan_to_num(d["spread"].to_numpy("float32"), nan=9.0)
        self.dte = d["dte"].to_numpy("float32")
        self.age = d["age"].to_numpy("float32")
        self.life = d["life"].to_numpy("float32")
        self.dvol7 = np.nan_to_num(d["dvol7"].to_numpy("float32"), nan=0.0)
        self.cumvol = d["cumvol"].to_numpy("float32")
        self.mom = {k: d[f"mom{k}"].to_numpy("float32") for k in (1, 3, 7)}
        self.ev_n = np.nan_to_num(d["ev_n"].to_numpy("float32"), nan=0.0)
        self.ev_sum = np.nan_to_num(d["ev_sum"].to_numpy("float32"), nan=0.0)
        self.ev_total = d["ev_total"].to_numpy("int32")
        self.fav = d["ev_fav"].to_numpy(bool)
        self.cat = d["category"].to_numpy(object)
        self.cats = sorted(set(self.cat))
        self.dow = ((d["ts"].to_numpy("int64") // 86400 + 4) % 7).astype("int8")          # 0 = Sunday
        self.month = (np.asarray(d["ts"].to_numpy("int64"), "datetime64[s]").astype("datetime64[M]").astype(int) % 12 + 1)
        self.base = self.q & (self.dte > 0.25) & (self.spread <= 0.10)                     # a tradable, live quote
        self.early = d["early"].to_numpy(bool) if "early" in d else np.zeros(p.n, bool)
        self.strike = d["strike_type"].fillna("none").to_numpy(object)
        self.has_strike = d["floor_strike"].notna().to_numpy() | d["cap_strike"].notna().to_numpy()
        self.lived = np.clip(self.age / np.maximum(self.life, 1e-6), 0, 1)                 # share of scheduled life elapsed

    def snapshot(self, days: float) -> np.ndarray:
        """One bar per market: the first tradable bar with `days` or fewer left. Unlike "the first bar at which the
        price is in a band", this does not depend on the path the price took, so it measures calibration of the
        price LEVEL at a fixed horizon and nothing else."""
        return np.isin(np.arange(self.p.n), self.p.first_per_market(self.base & (self.dte <= days)))

    def price(self, lo, hi):
        return (self.mid >= lo) & (self.mid < hi)

    def days(self, lo, hi):
        return (self.dte >= lo) & (self.dte < hi)


def name_range(lo, hi, unit=""):
    return f"{lo:g}-{hi:g}{unit}" if hi < 9000 else f"{lo:g}+{unit}"


# 1. Price-level calibration: is a contract at this price worth its price?
def f_calibration(f: Features):
    for (lo, hi), side, entry in itertools.product(PRICE, SIDES, ENTRIES):
        yield "1 calibration", f"mid {name_range(lo * 100, hi * 100, 'c')}", f.base & f.price(lo, hi), side, entry
    for (lo, hi), (d0, d1), side, entry in itertools.product(PRICE, DTE, SIDES, ENTRIES):
        yield ("1 calibration x days", f"mid {name_range(lo * 100, hi * 100, 'c')}, {name_range(d0, d1, 'd')} to close",
               f.base & f.price(lo, hi) & f.days(d0, d1), side, entry)
    for cat in f.cats:
        c = f.cat == cat
        for (lo, hi), side, entry in itertools.product(PRICE, SIDES, ENTRIES):
            yield "1 calibration x category", f"{cat}: mid {name_range(lo * 100, hi * 100, 'c')}", f.base & c & f.price(lo, hi), side, entry


# 1b. The same question asked cleanly: the price at a fixed number of days before close, whatever came before
def f_snapshot(f: Features):
    for h in (1, 3, 7, 14, 30, 60):
        snap = f.snapshot(h)
        for (lo, hi), side, entry in itertools.product(PRICE, SIDES, ENTRIES):
            yield "1b snapshot", f"{h}d before close: mid {name_range(lo * 100, hi * 100, 'c')}", snap & f.price(lo, hi), side, entry
        for lo, hi in ((0.0, 0.5), (0.5, 1.0), (0.2, 0.8)):
            for side, entry in itertools.product(SIDES, ENTRIES):
                yield "1b snapshot", f"{h}d before close: mid {name_range(lo * 100, hi * 100, 'c')}", snap & f.price(lo, hi), side, entry
    for h, cat in itertools.product((3, 14), f.cats):
        snap = f.snapshot(h) & (f.cat == cat)
        for (lo, hi), side, entry in itertools.product([(0.03, 0.2), (0.2, 0.5), (0.5, 0.8), (0.8, 0.97)], SIDES, ENTRIES):
            yield "1b snapshot x category", f"{cat}, {h}d before close: mid {name_range(lo * 100, hi * 100, 'c')}", snap & f.price(lo, hi), side, entry


# 2. Favourites near expiry ("bonds")
def f_bonds(f: Features):
    for thr, dmax, smax, entry in itertools.product((0.80, 0.85, 0.90, 0.93, 0.95, 0.97), (1, 2, 3, 7, 14, 30), (0.02, 0.05), ENTRIES):
        m = f.base & (f.dte <= dmax) & (f.spread <= smax)
        yield "2 bonds", f"YES at mid >= {thr * 100:g}c, <= {dmax}d, spread <= {smax * 100:g}c", m & (f.mid >= thr), "yes", entry
        yield "2 bonds", f"NO at mid <= {100 - thr * 100:g}c, <= {dmax}d, spread <= {smax * 100:g}c", m & (f.mid <= 1 - thr) & (f.mid > 0), "no", entry


# 3. Always No, by event size and by where in the event the market sits
def f_always_no(f: Features):
    sizes = [(1, 1), (2, 4), (5, 10), (11, 30), (31, 100000)]
    for (a, b), entry in itertools.product(sizes, ENTRIES):
        m = f.base & (f.ev_total >= a) & (f.ev_total <= b)
        tag = f"events of {a}" if a == b else f"events of {a}-{b}" if b < 1000 else f"events of {a}+"
        yield "3 always no", f"{tag} markets", m, "no", entry
        yield "3 always no", f"{tag} markets, not the favourite", m & ~f.fav, "no", entry
        yield "3 always no", f"{tag} markets, the favourite", m & f.fav, "no", entry
        yield "3 always yes", f"{tag} markets, the favourite", m & f.fav, "yes", entry
    for cat, entry in itertools.product(f.cats, ENTRIES):
        yield "3 always no x category", f"{cat}", f.base & (f.cat == cat), "no", entry
        yield "3 always no x category", f"{cat}, mid 20-80c", f.base & (f.cat == cat) & f.price(0.2, 0.8), "no", entry


# 4 and 13. Momentum, reversal and jumps
def f_momentum(f: Features):
    for k, x, entry in itertools.product((1, 3, 7), (0.03, 0.05, 0.10, 0.20), ENTRIES):
        mom = f.mom[k]
        live = f.base & f.price(0.08, 0.92)
        up, down = live & (mom >= x), live & (mom <= -x)
        yield "4 momentum", f"up {x * 100:g}c in {k}d: follow", up, "yes", entry
        yield "4 momentum", f"up {x * 100:g}c in {k}d: fade", up, "no", entry
        yield "4 momentum", f"down {x * 100:g}c in {k}d: follow", down, "no", entry
        yield "4 momentum", f"down {x * 100:g}c in {k}d: fade", down, "yes", entry


# 5. Deadline markets ("before ...", "by ..."): do they drift to No?
def f_deadline(f: Features, titles: np.ndarray):
    dead = np.array([bool(re.search(r"\b(before|by)\b", t or "", re.I)) for t in titles])
    for (lo, hi), (d0, d1), entry in itertools.product([(0.05, 0.2), (0.2, 0.5), (0.5, 0.8), (0.05, 0.95)], [(0, 7), (7, 30), (30, 10000)], ENTRIES):
        m = f.base & f.price(lo, hi) & f.days(d0, d1)
        tag = f"mid {name_range(lo * 100, hi * 100, 'c')}, {name_range(d0, d1, 'd')} to close"
        yield "5 deadline", f"deadline wording: {tag}", m & dead, "no", entry
        yield "5 deadline", f"no deadline wording: {tag}", m & ~dead, "no", entry


# 7. Attention: thin against busy, young against old
def f_attention(f: Features):
    vols = [(0, 50), (50, 500), (500, 5000), (5000, 1e12)]
    ages = [(0, 2), (2, 7), (7, 30), (30, 100000)]
    for (v0, v1), (lo, hi), side, entry in itertools.product(vols, [(0.05, 0.2), (0.2, 0.8), (0.8, 0.95)], SIDES, ENTRIES):
        yield ("7 volume", f"${name_range(v0, v1) if v1 < 1e11 else f'{v0:g}+'} traded in 7d, mid {name_range(lo * 100, hi * 100, 'c')}",
               f.base & (f.dvol7 >= v0) & (f.dvol7 < v1) & f.price(lo, hi), side, entry)
    for (a0, a1), (lo, hi), side, entry in itertools.product(ages, [(0.05, 0.2), (0.2, 0.8), (0.8, 0.95)], SIDES, ENTRIES):
        yield ("10 age", f"listed {name_range(a0, a1, 'd')} ago, mid {name_range(lo * 100, hi * 100, 'c')}",
               f.base & (f.age >= a0) & (f.age < a1) & f.price(lo, hi), side, entry)


# 8. Spread: does a wide quote pay the side that rests in it?
def f_spread(f: Features):
    for (s0, s1), (lo, hi), side, entry in itertools.product([(0, 0.011), (0.011, 0.03), (0.03, 0.06), (0.06, 0.15)],
                                                            [(0.05, 0.2), (0.2, 0.8), (0.8, 0.95)], SIDES, ENTRIES):
        m = f.q & (f.dte > 0.25) & (f.spread >= s0) & (f.spread < s1) & f.price(lo, hi)
        yield "8 spread", f"spread {name_range(s0 * 100, s1 * 100, 'c')}, mid {name_range(lo * 100, hi * 100, 'c')}", m, side, entry


# 12. Calendar
def f_calendar(f: Features):
    names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    for d, side, entry in itertools.product(range(7), SIDES, ENTRIES):
        yield "12 calendar", f"bar ends {names[d]}, mid 20-80c", f.base & (f.dow == d) & f.price(0.2, 0.8), side, entry
    for mth, side in itertools.product(range(1, 13), SIDES):
        yield "12 calendar", f"month {mth}, mid 20-80c", f.base & (f.month == mth) & f.price(0.2, 0.8), side, "tk"


# 6. Threshold ladders: "above X" for rising X inside one event must be priced in order
def f_ladder(f: Features):
    d = f.p.df
    pair_cost = np.nan_to_num(d["pair_cost"].to_numpy("float32"), nan=9.0)
    up_mid = np.nan_to_num(d["up_mid"].to_numpy("float32"), nan=-9.0)
    live = f.q & (f.dte > 0.25)
    for x in (0.0, 0.01, 0.02, 0.05):
        # buy YES on this rung and NO on the next rung up for less than the 1 it must pay: a lock, if it fills
        yield "6 ladder", f"pair costs under {1 - x:.2f} after fees", live & (pair_cost < 1 - x), "pair", "pair"
    for eps in (0.0, 0.02, 0.05):
        inv = live & (up_mid >= f.mid + eps) & (f.mid > 0)
        dn_mid = np.nan_to_num(d["dn_mid"].to_numpy("float32"), nan=9.0)
        inv_no = live & (f.mid >= dn_mid + eps) & (dn_mid > 0)
        for entry in ENTRIES:
            yield "6 ladder", f"next rung up priced {eps * 100:g}c or more ABOVE this one: buy this rung", inv, "yes", entry
            yield "6 ladder", f"this rung priced {eps * 100:g}c or more ABOVE the rung below: buy NO on this rung", inv_no, "no", entry


# 16. Markets that can close early ("will X happen before ...") against markets with a fixed date
def f_early(f: Features):
    for (lo, hi), early, side, entry in itertools.product(PRICE, (True, False), SIDES, ENTRIES):
        yield ("16 early close", f"{'can close early' if early else 'fixed date'}: mid {name_range(lo * 100, hi * 100, 'c')}",
               f.base & (f.early == early) & f.price(lo, hi), side, entry)


# 18. The shape of the question: "above X", "below X", "between X and Y", or no number at all
def f_strike(f: Features):
    kinds = [k for k in sorted(set(f.strike)) if (f.strike == k).sum() >= 2000]
    for kind, (lo, hi), side, entry in itertools.product(kinds, [(0, 0.05), (0.05, 0.2), (0.2, 0.5), (0.5, 0.8), (0.8, 0.95), (0.95, 1)],
                                                         SIDES, ENTRIES):
        yield ("18 question shape", f"strike type {kind}: mid {name_range(lo * 100, hi * 100, 'c')}",
               f.base & (f.strike == kind) & f.price(lo, hi), side, entry)


# 19. Longshots by how many outcomes the event has
def f_event_size(f: Features):
    sizes = [(1, 1), (2, 4), (5, 10), (11, 100000)]
    for (a, b), (lo, hi), side, entry in itertools.product(sizes, [(0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.80, 0.95), (0.95, 1)],
                                                           SIDES, ENTRIES):
        tag = f"events of {a}" if a == b else f"events of {a}-{b}" if b < 1000 else f"events of {a}+"
        yield ("19 price x event size", f"{tag} markets: mid {name_range(lo * 100, hi * 100, 'c')}",
               f.base & (f.ev_total >= a) & (f.ev_total <= b) & f.price(lo, hi), side, entry)


# 22. Outcomes of one event priced to more or less than 1 in total (events without numeric strikes only: a
#     ladder of "above X" questions adds up to far more than 1 by construction). A proxy: the download does not
#     carry Kalshi's own "mutually exclusive" flag yet.
def f_event_sum(f: Features):
    cat_event = f.base & ~f.has_strike & (f.ev_n >= 3)
    for x, entry in itertools.product((1.03, 1.06, 1.10, 1.20), ENTRIES):
        over = cat_event & (f.ev_sum >= x)
        yield "22 event sum", f"3+ outcomes priced to {x:.2f} or more in total: NO on the non-favourites", over & ~f.fav, "no", entry
        yield "22 event sum", f"3+ outcomes priced to {x:.2f} or more in total: NO on the favourite", over & f.fav, "no", entry
    for x, entry in itertools.product((0.97, 0.94, 0.90), ENTRIES):
        under = cat_event & (f.ev_sum <= x) & (f.ev_sum > 0.5)
        yield "22 event sum", f"3+ outcomes priced to {x:.2f} or less in total: YES on the favourite", under & f.fav, "yes", entry
        yield "22 event sum", f"3+ outcomes priced to {x:.2f} or less in total: YES on the non-favourites", under & ~f.fav, "yes", entry


# 23. How much had traded SO FAR (known at the time, unlike lifetime volume)
def f_cumvol(f: Features):
    vols = [(0, 1000), (1000, 10000), (10000, 100000), (100000, 1e15)]
    for (v0, v1), (lo, hi), side, entry in itertools.product(vols, [(0, 0.05), (0.05, 0.2), (0.2, 0.8), (0.8, 0.95), (0.95, 1)], SIDES, ENTRIES):
        tag = f"{v0:g}+" if v1 > 1e14 else f"{v0:g}-{v1:g}"
        yield ("23 traded so far", f"{tag} contracts so far: mid {name_range(lo * 100, hi * 100, 'c')}",
               f.base & (f.cumvol >= v0) & (f.cumvol < v1) & f.price(lo, hi), side, entry)


# 24. Where in its scheduled life the market is
def f_life(f: Features):
    for (a, b), (lo, hi), side, entry in itertools.product([(0, 0.1), (0.1, 0.5), (0.5, 0.9), (0.9, 1.01)],
                                                           [(0, 0.05), (0.05, 0.2), (0.2, 0.8), (0.8, 0.95), (0.95, 1)], SIDES, ENTRIES):
        yield ("24 share of life", f"{a:.0%}-{min(b, 1):.0%} of scheduled life elapsed: mid {name_range(lo * 100, hi * 100, 'c')}",
               f.base & (f.lived >= a) & (f.lived < b) & f.price(lo, hi), side, entry)


# 25. Selling longshots (buying NO under 10c), crossed with everything that might sharpen or spoil it
def f_longshot(f: Features):
    for (lo, hi), entry in itertools.product([(0.0, 0.03), (0.03, 0.06), (0.06, 0.10), (0.10, 0.15)], ENTRIES):
        cheap = f.base & (f.mid > lo) & (f.mid <= hi)
        tag = f"NO at mid {name_range(lo * 100, hi * 100, 'c')}"
        for (d0, d1) in [(0, 7), (7, 30), (30, 90), (90, 10000)]:
            for early in (True, False):
                yield ("25 longshot NO", f"{tag}, {name_range(d0, d1, 'd')} to scheduled end, {'can close early' if early else 'fixed date'}",
                       cheap & f.days(d0, d1) & (f.early == early), "no", entry)
        for k, sign in itertools.product((1, 7), (1, -1)):
            mom = f.mom[k]
            yield ("25 longshot NO", f"{tag}, {'up' if sign > 0 else 'down'} 1c+ in {k}d",
                   cheap & ((mom >= 0.01) if sign > 0 else (mom <= -0.01)), "no", entry)
        for v0, v1 in [(0, 200), (200, 2000), (2000, 1e15)]:
            yield ("25 longshot NO", f"{tag}, ${v0:g}{'+' if v1 > 1e14 else '-' + format(v1, 'g')} traded in 7d",
                   cheap & (f.dvol7 >= v0) & (f.dvol7 < v1), "no", entry)
        for s0, s1 in [(0, 0.011), (0.011, 0.03), (0.03, 0.10)]:
            yield ("25 longshot NO", f"{tag}, spread {name_range(s0 * 100, s1 * 100, 'c')}", cheap & (f.spread >= s0) & (f.spread < s1), "no", entry)
        for fav in (True, False):
            yield ("25 longshot NO", f"{tag}, {'the favourite' if fav else 'not the favourite'} of a 3+ market event",
                   cheap & (f.ev_total >= 3) & (f.fav == fav), "no", entry)


# 26. The favourite-longshot bias as one rule: buy the dear side of any contract whose cheap side is under x
def f_dear_side(f: Features):
    for x, (d0, d1), smax, entry in itertools.product((0.10, 0.20, 0.35, 0.50), [(0, 10000), (0, 30), (30, 10000)], (0.03, 0.10), ENTRIES):
        m = f.base & f.days(d0, d1) & (f.spread <= smax)
        tag = f"{'any time' if d1 > 9000 and d0 == 0 else name_range(d0, d1, 'd') + ' to scheduled end'}, spread <= {smax * 100:g}c"
        yield "26 dear side", f"NO where YES is at {x * 100:g}c or less, {tag}", m & (f.mid > 0) & (f.mid <= x), "no", entry
        yield "26 dear side", f"YES where YES is at {100 - x * 100:g}c or more, {tag}", m & (f.mid >= 1 - x), "yes", entry
    for (lo, hi), entry in itertools.product([(0.05, 0.35), (0.05, 0.20), (0.10, 0.35), (0.03, 0.50)], ENTRIES):
        yield "26 dear side", f"NO where YES is at {name_range(lo * 100, hi * 100, 'c')}", f.base & f.price(lo, hi), "no", entry
        yield "26 dear side", f"YES where YES is at {name_range(100 - hi * 100, 100 - lo * 100, 'c')}", f.base & f.price(1 - hi, 1 - lo), "yes", entry


# 14. Combinations of the single-factor conditions
def f_combos(f: Features):
    price = [(0.03, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 0.90), (0.90, 0.97)]
    days = [(0, 2), (2, 7), (7, 30), (30, 10000)]
    vols = [(0, 500), (500, 1e12)]
    for (lo, hi), (d0, d1), cat, side, entry in itertools.product(price, days, f.cats, SIDES, ENTRIES):
        yield ("14 price x days x category", f"{cat}: mid {name_range(lo * 100, hi * 100, 'c')}, {name_range(d0, d1, 'd')} to close",
               f.base & (f.cat == cat) & f.price(lo, hi) & f.days(d0, d1), side, entry)
    for (lo, hi), (d0, d1), (v0, v1), side, entry in itertools.product(price, days, vols, SIDES, ENTRIES):
        tag = "thin" if v1 < 1e11 else "busy"
        yield ("14 price x days x volume", f"{tag} (7d ${v0:g}{'-' + format(v1, 'g') if v1 < 1e11 else '+'}): mid "
               f"{name_range(lo * 100, hi * 100, 'c')}, {name_range(d0, d1, 'd')} to close",
               f.base & (f.dvol7 >= v0) & (f.dvol7 < v1) & f.price(lo, hi) & f.days(d0, d1), side, entry)
    for (lo, hi), (d0, d1), fav, side, entry in itertools.product(price, days, (True, False), SIDES, ENTRIES):
        multi = f.ev_total >= 3
        yield ("14 price x days x favourite", f"{'favourite' if fav else 'not favourite'} of a 3+ market event: mid "
               f"{name_range(lo * 100, hi * 100, 'c')}, {name_range(d0, d1, 'd')} to close",
               f.base & multi & (f.fav == fav) & f.price(lo, hi) & f.days(d0, d1), side, entry)
    for (lo, hi), k, sign, side, entry in itertools.product(price, (1, 3, 7), (1, -1), SIDES, ENTRIES):
        mom = f.mom[k]
        m = f.base & f.price(lo, hi) & ((mom >= 0.03) if sign > 0 else (mom <= -0.03))
        yield ("14 price x momentum", f"mid {name_range(lo * 100, hi * 100, 'c')}, {'up' if sign > 0 else 'down'} 3c+ in {k}d", m, side, entry)


def all_rules(f: Features, titles: np.ndarray):
    yield from f_calibration(f)
    yield from f_snapshot(f)
    yield from f_bonds(f)
    yield from f_always_no(f)
    yield from f_momentum(f)
    yield from f_deadline(f, titles)
    yield from f_attention(f)
    yield from f_spread(f)
    yield from f_calendar(f)
    yield from f_ladder(f)
    yield from f_combos(f)
    yield from f_early(f)
    yield from f_strike(f)
    yield from f_event_size(f)
    yield from f_event_sum(f)
    yield from f_cumvol(f)
    yield from f_life(f)
    yield from f_longshot(f)
    yield from f_dear_side(f)


# 11. Persistence: is a series that paid one side in the first half still paying it in the second?
PERSIST_BASES = [("NO at mid 20-80c", 0.20, 0.80, "no"), ("YES at mid 20-80c", 0.20, 0.80, "yes"),
                 ("NO at mid 3-20c", 0.03, 0.20, "no"), ("YES at mid 80-97c", 0.80, 0.97, "yes"),
                 ("NO at mid 80-97c", 0.80, 0.97, "no"), ("YES at mid 3-20c", 0.03, 0.20, "yes")]


def persistence(f: Features, min_events: int = 15, t_select: float = 2.0):
    """For each base rule and entry: pick the series whose in-sample result was positive with t >= t_select, then
    report the POOLED result of those series. The in-sample half is selected-on and means nothing; the
    out-of-sample half is the test. Yields (family, name, mask, side, entry, n_series_selected)."""
    p = f.p
    series = p.df["series"].to_numpy(object)
    codes, names = np.unique(series, return_inverse=True)[::-1]
    for (label, lo, hi, side), entry in itertools.product(PERSIST_BASES, ENTRIES):
        base = f.base & f.price(lo, hi) & p.ok[(side, entry)]
        rows = p.first_per_market(base)
        rows_is = rows[~p.oos[rows]]
        if rows_is.size == 0:
            continue
        r = p.r[(side, entry)][rows_is].astype("float64")
        sc = codes[rows_is]
        chosen = []
        for c in np.unique(sc):
            sel = sc == c
            x = r[sel]
            ev = p.event[rows_is][sel]
            k = np.unique(ev).size
            if k < min_events:
                continue
            m = x.mean()
            sums = np.bincount(np.unique(ev, return_inverse=True)[1], weights=x - m)
            se = np.sqrt((sums ** 2).sum()) / x.size
            if se > 0 and m > 0 and m / se >= t_select:
                chosen.append(c)
        if not chosen:
            continue
        mask = base & np.isin(codes, chosen)
        yield "11 persistence", f"series that paid in sample: {label}", mask, side, entry, len(chosen)
