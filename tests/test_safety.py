import pandas as pd
import pytest

from src import safety

SLEEVE = ("IEF", "GLD")


def _book(n=45, w=0.02, held_frac=1.0, equity=100_000.0):
    """n stock targets at weight w; the account holds the first held_frac of them at target, plus IEF/GLD."""
    names = [f"S{i:02d}" for i in range(n)]
    tgt = pd.Series(w, index=names)
    tgt["IEF"], tgt["GLD"] = 0.0, 0.0
    held = names[: int(n * held_frac)]
    pos = pd.Series(w * equity, index=held, dtype=float)
    prices = pd.Series(50.0, index=names)
    return tgt, pos, prices


@pytest.fixture(autouse=True)
def _paper_env(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER", "true")
    monkeypatch.delenv(safety.LIVE_CONFIRM_ENV, raising=False)


def check(tgt, pos, prices, equity=100_000.0, prev=100_000.0, prev_prices=None, tmp_path=None, **kw):
    return safety.check_orders(tgt, pos, equity, prev, prices, prev_prices if prev_prices is not None else prices,
                               {}, sleeve_assets=SLEEVE, root=tmp_path or ".", **kw)


def test_a_normal_day_passes(tmp_path):
    tgt, pos, px = _book()
    tgt["S00"], tgt["S44"] = 0.0, 0.0            # two exits, two new names
    tgt["N1"], tgt["N2"] = 0.02, 0.02
    px["N1"], px["N2"] = 20.0, 30.0
    r = check(tgt, pos, px, tmp_path=tmp_path)
    assert r.ok, r.summary()
    assert r.stats["n_stocks"] == 45 and r.stats["stock_turnover"] == pytest.approx(0.08)
    assert "PASS" in r.summary()


def test_real_money_needs_the_confirmation(monkeypatch, tmp_path):
    tgt, pos, px = _book()
    monkeypatch.setenv("ALPACA_PAPER", "false")
    r = check(tgt, pos, px, tmp_path=tmp_path)
    assert not r.ok and "real-money" in r.stops[0]
    with pytest.raises(safety.SafetyStop):
        safety.require_live_confirmation()
    monkeypatch.setenv(safety.LIVE_CONFIRM_ENV, "yes")                  # anything but the exact phrase
    assert not check(tgt, pos, px, tmp_path=tmp_path).ok
    monkeypatch.setenv(safety.LIVE_CONFIRM_ENV, safety.LIVE_CONFIRM_VALUE)
    assert check(tgt, pos, px, tmp_path=tmp_path).ok
    safety.require_live_confirmation()                                   # no raise


def test_paper_never_needs_the_confirmation():
    safety.require_live_confirmation()


def test_kill_switch(tmp_path):
    tgt, pos, px = _book()
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "STOP").write_text("")
    r = check(tgt, pos, px, tmp_path=tmp_path)
    assert not r.ok and "kill switch" in r.stops[0]


def test_equity_sanity(tmp_path):
    tgt, pos, px = _book()
    assert not check(tgt, pos, px, equity=0.0, tmp_path=tmp_path).ok
    r = check(tgt, pos * 0.7, px, equity=70_000.0, prev=100_000.0, tmp_path=tmp_path)
    assert not r.ok and "equity" in r.stops[0]
    assert check(tgt, pos * 0.9, px, equity=90_000.0, prev=100_000.0, tmp_path=tmp_path).ok   # a bad day, not a glitch
    r = check(tgt, pos * 0.7, px, equity=70_000.0, prev=100_000.0, tmp_path=tmp_path, allow_rebuild=True)
    assert r.ok and r.warnings
    assert check(tgt, pos, px, prev=None, tmp_path=tmp_path).ok                               # first run: no history


def test_position_count(tmp_path):
    tgt, pos, px = _book(n=20, w=0.045)
    r = check(tgt, pos, px, tmp_path=tmp_path)
    assert not r.ok and "stock targets" in r.stops[0]
    tgt, pos, px = _book(n=70, w=0.013)
    assert not check(tgt, pos, px, tmp_path=tmp_path).ok


def test_one_huge_stock_order_stops_but_a_big_sleeve_swap_does_not(tmp_path):
    tgt, pos, px = _book()
    tgt["S01"] = 0.20                                  # a bug: 18% more of one stock
    r = check(tgt, pos, px, tmp_path=tmp_path)
    assert not r.ok and "S01" in r.stops[0]
    tgt, pos, px = _book(w=0.01)                      # exposure layer: stocks 45%, sleeve 50% -> 10% IEF to GLD
    pos["IEF"], pos["GLD"] = 40_000.0, 10_000.0
    tgt["IEF"], tgt["GLD"] = 0.30, 0.20
    r = check(tgt, pos, px, tmp_path=tmp_path)
    assert r.ok, r.summary()
    tgt["IEF"], tgt["GLD"] = 0.0, 0.95                 # a sleeve order of 85%+ of equity stops
    pos["GLD"] = 0.0
    assert not check(tgt, pos, px, tmp_path=tmp_path).ok


def test_turnover_cap_and_the_rebuild_flag(tmp_path):
    tgt, _, px = _book()
    empty = pd.Series(dtype=float)                    # fresh or reset account: the whole book is bought at once
    r = check(tgt, empty, px, tmp_path=tmp_path)
    assert r.ok   # 90% of equity is at the stock limit, not above it
    tgt2 = pd.Series(0.021, index=tgt.index[:45])
    tgt2["IEF"] = 0.0
    r = check(tgt2, empty, px, tmp_path=tmp_path)
    assert not r.ok and "turnover" in r.stops[0]
    assert check(tgt2, empty, px, tmp_path=tmp_path, allow_rebuild=True).ok
    # sell the whole book and buy a different one: 180% stock turnover, a stop even if each order is small
    old = pd.Series(0.02 * 100_000, index=[f"S{i:02d}" for i in range(45)])
    new = pd.Series(0.02, index=[f"X{i:02d}" for i in range(45)])
    r = check(new, old, pd.Series(50.0, index=new.index.union(old.index)), tmp_path=tmp_path)
    assert not r.ok and any("turnover" in s for s in r.stops)


def test_price_jump_skips_that_name_only(tmp_path):
    tgt, pos, px = _book()
    tgt["S00"] = 0.0                                   # exit
    tgt["N1"] = 0.02                                   # new name with a broken price
    prev = px.copy()
    px["N1"], prev["N1"] = 80.0, 20.0
    px["S00"], prev["S00"] = 5.0, 50.0                 # held name crashed 90%: no sell on a bad print either
    r = check(tgt, pos, px, prev_prices=prev, tmp_path=tmp_path)
    assert r.ok
    assert r.skip == {"N1", "S00"} and len(r.warnings) == 2
    assert r.stats["stock_turnover"] == 0.0


def test_missing_price_skips_a_buy_but_not_a_sell(tmp_path):
    tgt, pos, px = _book()
    tgt["S00"] = 0.0
    tgt["N1"] = 0.02
    px = px.drop("S00")
    r = check(tgt, pos, px, tmp_path=tmp_path)
    assert r.skip == {"N1"} and r.ok


def test_buys_never_exceed_cash_plus_sells(tmp_path):
    tgt, pos, px = _book()                             # fully invested in 45 names at 2% = 90%, cash 10%
    for i in range(40, 45):
        tgt[f"S{i:02d}"] = 0.06                         # wants +4% in five names = +20% of equity
    r = check(tgt, pos, px, tmp_path=tmp_path)
    assert r.ok and any("scaled" in w for w in r.warnings)
    buys = sum((r.targets[f"S{i:02d}"] - 0.02) * 100_000 for i in range(40, 45))
    assert buys == pytest.approx(10_000.0)              # exactly the cash on hand


def test_previous_equity_reads_the_last_earlier_session(tmp_path):
    p = tmp_path / "equity.csv"
    assert safety.previous_equity(p, "2026-11-17") is None
    p.write_text("date,equity,cash,n_positions\n2026-11-13,98263.88,1972.2,45\n2026-11-16,97498.09,1000.5,45\n"
                 "2026-11-17,97000,900,45\n")
    assert safety.previous_equity(p, pd.Timestamp("2026-11-17")) == pytest.approx(97498.09)
    assert safety.previous_equity(p, pd.Timestamp("2026-11-18 10:00")) == pytest.approx(97000.0)


def test_alpaca_submit_refuses_real_money_without_confirmation(monkeypatch):
    from src.broker import AlpacaBroker

    class _Client:
        cancelled = 0

        def cancel_orders(self):
            self.cancelled += 1

    b = AlpacaBroker.__new__(AlpacaBroker)
    b.client, b.order_type = _Client(), "market"
    monkeypatch.setenv("ALPACA_PAPER", "false")
    with pytest.raises(safety.SafetyStop):
        b.submit_targets(pd.Series({"AAA": 0.5}))
    assert b.client.cancelled == 0                     # stopped before touching the account at all
