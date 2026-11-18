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


def all_rules(f: Features, titles: np.ndarray):
    yield from f_calibration(f)
    yield from f_bonds(f)
    yield from f_always_no(f)
    yield from f_momentum(f)
    yield from f_deadline(f, titles)
    yield from f_attention(f)
    yield from f_spread(f)
    yield from f_calendar(f)
