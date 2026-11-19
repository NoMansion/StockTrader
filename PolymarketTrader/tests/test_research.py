"""The backtest engine on a made-up exchange where the truth is known: prices are fair except for one planted
bias, and the engine must find that bias and nothing else."""
import sqlite3
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research"))

import panel  # noqa: E402
from backtest import Panel, row, verdict  # noqa: E402
from families import Features, all_rules  # noqa: E402
from kalshi_download import SCHEMA, shuffle_key  # noqa: E402

DAY = 86400


def make_db(path, n_events=1500, seed=7, longshot_bias=0.0):
    """Each event has 3 markets; each market lives 12 daily bars. The true probability follows a random walk and
    the quoted mid equals it, except that contracts under 30 cents are quoted `longshot_bias` too high."""
    rng = np.random.default_rng(seed)
    db = sqlite3.connect(str(path))
    db.executescript(SCHEMA)
    db.execute("INSERT INTO series VALUES ('S', 'Economics', 'Test', 'quadratic', 1, 'daily', '', 1)")
    t0 = panel.SPLIT_TS - 190 * DAY                             # closes straddle the in/out-of-sample date
    for e in range(n_events):
        close = t0 + e * 6 * 3600 + 14 * DAY
        for j in range(3):
            tk = f"S-{e}-{j}"
            p = float(rng.uniform(0.04, 0.96))
            bars = []
            for b in range(12):
                # a true martingale that stays inside (0, 1): the step shrinks near the edges instead of clipping,
                # so the outcome drawn from the last value is fairly priced at every earlier bar
                p = float(p + rng.uniform(-1, 1) * 0.25 * min(p, 1 - p))
                mid = p + (longshot_bias if p < 0.30 else 0.0)
                bid, ask = round(mid - 0.01, 2), round(mid + 0.01, 2)
                ts = close - (12 - b) * DAY
                bars.append((tk, ts, bid, ask, bid, bid, ask, ask, mid, mid, mid, 100.0, 500.0, bid, ask, mid))
            y = "yes" if rng.random() < p else "no"
            db.execute("INSERT INTO markets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,0)",
                       (tk, "S", f"S-{e}", "Economics", f"Will {tk} happen before June?", "x", close - 13 * DAY, close, y,
                        1.0 if y == "yes" else 0.0, 5000.0, 500.0, 0.5, None, None, None, "hist", shuffle_key(tk), close + 3600))
            db.executemany("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", bars)
    db.commit()
    db.close()


@pytest.fixture(scope="module")
def fair(tmp_path_factory):
    path = tmp_path_factory.mktemp("research") / "fair.db"
    make_db(path)
    return panel.load(path)


def test_panel_keeps_signal_and_execution_apart(fair):
    df = fair
    assert len(df) == 1500 * 3 * 12 and df["quoted"].mean() > 0.9
    one = df[df["ticker"] == "S-0-0"].reset_index(drop=True)
    # the taker price of bar t is the NEXT bar's opening ask; the last bar has no next bar and so no taker trade
    assert one.loc[0, "n_ask_op"] == pytest.approx(one.loc[1, "ask_op"])
    assert np.isnan(one.loc[11, "r_yes_tk"]) and not one.loc[11, "n_ok"]
    y, ask = one.loc[0, "y"], one.loc[1, "ask_op"]
    cost = ask + 0.07 * ask * (1 - ask)
    assert one.loc[0, "r_yes_tk"] == pytest.approx((y - cost) / cost, rel=1e-4)
    assert one.loc[3, "mom1"] == pytest.approx(one.loc[3, "mid"] - one.loc[2, "mid"], abs=1e-6)
    assert one["dte"].iloc[0] == pytest.approx(12.0) and one["ev_total"].iloc[0] == 3
    assert "oos" in df and df["oos"].any() and (~df["oos"]).any()


def test_one_entry_per_market_and_event_clustering(fair):
    p = Panel(fair)
    f = Features(p)
    ins, oos = p.evaluate(f.base, "yes", "tk")
    assert 0.9 * 4500 < ins.n + oos.n <= 4500                  # every quoted market entered exactly once
    assert 1400 < ins.events + oos.events <= 1500
    every, _ = p.evaluate(f.base, "yes", "tk", once=False)
    assert every.n > ins.n * 5


def test_fair_prices_lose_the_costs_and_nothing_passes(fair):
    p = Panel(fair)
    f = Features(p)
    ins, oos = p.evaluate(f.base & f.price(0.35, 0.65), "yes", "tk")
    assert -0.12 < ins.ret < 0.02 and -0.12 < oos.ret < 0.02    # about the spread and the fee, not a windfall
    titles = np.array(["Will x happen before June?"] * len(fair), dtype=object)
    rows = []
    for family, name, mask, side, entry in all_rules(f, titles):
        a, b = p.evaluate(mask, side, entry)
        r = row(family, name, side, entry, a, b)
        r["verdict"] = verdict(r)
        rows.append(r)
    out = pd.DataFrame(rows)
    assert len(out) > 1000
    takers = out[out["entry"] == "tk"]
    assert (takers["verdict"] == "pass").sum() == 0             # no taker rule beats fair prices after costs
    judged = takers[takers["verdict"] != "thin"]
    assert len(judged) > 50 and judged["is_ret"].mean() < -0.01  # on average they lose the spread and the fee
    assert (takers["verdict"] == "loses").sum() >= 1


def test_a_planted_bias_is_found_on_the_right_side(tmp_path):
    path = tmp_path / "biased.db"
    make_db(path, n_events=6000, longshot_bias=0.06)            # cheap contracts quoted 6 cents too high
    df = panel.load(path)
    p = Panel(df)
    f = Features(p)
    ins, oos = p.evaluate(f.base & f.price(0.08, 0.30), "no", "tk")     # selling them should pay
    r = row("x", "sell longshots", "no", "tk", ins, oos)
    assert ins.ret > 0.01 and oos.ret > 0.01 and oos.t > 3 and verdict(r) == "pass"
    ins2, oos2 = p.evaluate(f.base & f.price(0.08, 0.30), "yes", "tk")  # and buying them should lose badly
    assert oos2.ret < -0.15 and oos2.t < -3


def test_account_replay_locks_money_until_settlement(tmp_path):
    import portfolio
    path = tmp_path / "biased.db"
    make_db(path, n_events=3000, longshot_bias=0.06)
    p = Panel(panel.load(path))
    f = Features(p)
    good = [(f.base & f.price(0.08, 0.30), "no", "tk")]
    bad = [(f.base & f.price(0.08, 0.30), "yes", "tk")]
    ins, oos = portfolio.run(p, good, stake_frac=0.01, event_cap=0.03, max_exposure=0.5)
    assert oos.bets > 300 and oos.total > 0 and oos.max_dd < 0.25 and 0 < oos.exposure <= 0.5
    _, lose = portfolio.run(p, bad, stake_frac=0.01, event_cap=0.03, max_exposure=0.5)
    assert lose.total < 0
    # a tighter exposure cap means fewer bets are taken
    _, tight = portfolio.run(p, good, stake_frac=0.01, event_cap=0.03, max_exposure=0.05)
    assert tight.bets < oos.bets and tight.skipped > 0
    # one bet, by hand: $1,000, 1% stake, return +20% -> $1,002
    one = portfolio.simulate(np.array([[0.0, 86400.0, 0.20, 1.0]]), stake_frac=0.01)
    assert one.bets == 1 and one.total == pytest.approx(0.002)


def test_only_the_random_sample_is_used_by_default(tmp_path):
    """Markets downloaded out of shuffle order (the old biggest-first way) sit beyond the first unattempted key and
    must not enter a backtest unless asked for."""
    path = tmp_path / "s.db"
    make_db(path, n_events=60)
    db = sqlite3.connect(str(path))
    keys = sorted(r[0] for r in db.execute("SELECT rnd FROM markets"))
    cut = keys[len(keys) // 2]
    # pretend the half with the larger keys has not been attempted, except five "big" markets fetched out of order
    db.execute("UPDATE markets SET candles_done=0 WHERE rnd >= ?", (cut,))
    db.execute("UPDATE markets SET candles_done=1 WHERE ticker IN (SELECT ticker FROM markets WHERE rnd >= ? ORDER BY rnd DESC LIMIT 5)", (cut,))
    db.commit()
    db.close()
    rnd_sample = panel.load(path)
    everything = panel.load(path, sample="all")
    assert rnd_sample["ticker"].nunique() == len(keys) // 2
    assert everything["ticker"].nunique() == len(keys) // 2 + 5


def test_the_liquid_census_shows_a_market_only_from_the_day_it_qualified(tmp_path):
    """A market downloaded because it ended up big must not lend its early, quiet days to a backtest."""
    path = tmp_path / "l.db"
    make_db(path, n_events=40)
    db = sqlite3.connect(str(path))
    db.execute("UPDATE markets SET volume=1200")                    # what the 12 bars of 100 add up to
    db.execute("UPDATE markets SET volume=300, candles_done=0 WHERE ticker='S-0-0'")    # a small one not fetched yet
    db.commit()
    liquid = panel.load(path, sample="liquid", min_cumvol=600)
    assert liquid["cumvol"].min() >= 600 and liquid.groupby("ticker")["bar"].min().eq(5).all()
    assert liquid["ticker"].nunique() == 40 * 3 - 1
    assert liquid["mom3"].notna().any()                             # signals may still look back before that day
    # default level: the lowest one the download is complete at
    assert panel.load(path, sample="liquid")["cumvol"].min() >= 300
    # one market of 1,200 contracts not fetched: the census is not complete at 600, so the category is left out
    db.execute("UPDATE markets SET candles_done=0 WHERE ticker='S-1-0'")
    db.commit()
    db.close()
    assert panel.load(path, sample="liquid", min_cumvol=600).empty


def test_days_to_close_come_from_the_schedule_not_from_an_early_close(tmp_path):
    """A market that closed early must not tell a rule, through 'days to close', that its event was about to happen."""
    path = tmp_path / "e.db"
    make_db(path, n_events=20)
    db = sqlite3.connect(str(path))
    close = db.execute("SELECT close_ts FROM markets WHERE ticker='S-0-0'").fetchone()[0]
    db.execute("UPDATE markets SET early=1, exp_ts=? WHERE ticker='S-0-0'", (close + 400 * DAY,))
    db.execute("UPDATE markets SET early=NULL WHERE ticker='S-1-0'")           # schedule not downloaded yet
    db.commit()
    db.close()
    d = panel.load(path, sample="all")
    e = d[d["ticker"] == "S-0-0"]
    assert e["dte"].min() > 399 and e["dte_real"].min() < 2 and e["early"].all()
    other = d[d["ticker"] == "S-0-1"]
    assert (other["dte"] == other["dte_real"]).all() and other["sched_known"].all()
    assert not d[d["ticker"] == "S-1-0"]["sched_known"].any()


def test_same_day_bets_are_not_ordered_by_how_they_ended(fair):
    """With a cap per event the account cannot take every bet of a day. Which ones it takes must not depend on the
    outcome: sorting ties by return put the losers first."""
    import portfolio
    p = Panel(fair)
    f = Features(p)
    b = pd.DataFrame(portfolio.entries(p, [(f.base, "no", "tk")]), columns=["ts", "close", "r", "event"])
    assert (b["ts"].diff().dropna() >= 0).all()                            # still in time order
    days = [g["r"].to_numpy() for _, g in b.groupby("ts") if len(g) == 3 and len(set(g["r"])) == 3]
    assert len(days) > 200
    ascending = np.mean([(np.diff(r) > 0).all() for r in days])
    assert ascending < 0.4                                                 # about 1 in 6 by chance; it was all of them
