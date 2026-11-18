import pytest

from src import safety, scoring

CFG = {"account": {"mode": "paper"}, "safety": {}}
NOW = 1_000_000.0


def acct(**kw):
    base = dict(cfg=CFG, equity=1000.0, prev_equity=1000.0, high_water=1000.0, deposited=1000.0)
    base.update(kw)
    return safety.check_account(**base)


def test_account_passes_when_nothing_is_wrong(tmp_path):
    res = acct(root=tmp_path)
    assert res.ok and res.exits_ok and "PASS" in res.summary()


def test_kill_switch_stops_everything(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "STOP").write_text("x")
    res = acct(root=tmp_path)
    assert not res.ok and not res.exits_ok and "kill switch" in res.stops[0]


def test_live_needs_explicit_confirmation(tmp_path, monkeypatch):
    live = {"account": {"mode": "live"}}
    monkeypatch.delenv(safety.LIVE_CONFIRM_ENV, raising=False)
    res = acct(cfg=live, root=tmp_path)
    assert not res.ok and not res.exits_ok
    with pytest.raises(safety.SafetyStop):
        safety.require_live_confirmation(live)
    monkeypatch.setenv(safety.LIVE_CONFIRM_ENV, safety.LIVE_CONFIRM_VALUE)
    assert acct(cfg=live, root=tmp_path).ok
    safety.require_live_confirmation(live)
    safety.require_live_confirmation(CFG)          # paper never needs it


def test_drawdown_and_total_loss_halt_entries_but_allow_exits(tmp_path):
    res = acct(equity=840.0, prev_equity=850.0, root=tmp_path)
    assert not res.ok and res.exits_ok and any("drawdown" in s for s in res.stops)
    res = acct(equity=690.0, prev_equity=700.0, high_water=700.0, root=tmp_path)
    assert any("experiment stop" in s for s in res.stops)


def test_equity_jump_is_treated_as_bad_data(tmp_path):
    res = acct(equity=1000.0, prev_equity=700.0, root=tmp_path)
    assert not res.ok and any("check the marks" in s for s in res.stops)


def test_daily_budget_is_routine_not_a_stop(tmp_path):
    full = acct(orders_24h=6, root=tmp_path)
    assert full.ok and not full.entries_ok and "daily budget" in full.notes[0]
    spent = acct(deployed_24h=100.0, root=tmp_path)
    assert spent.ok and not spent.entries_ok
    some = acct(orders_24h=5, deployed_24h=60.0, root=tmp_path)
    assert some.entries_ok and some.orders_left == 1 and some.usd_left == pytest.approx(40.0)


def test_zero_equity(tmp_path):
    assert not acct(equity=0.0, root=tmp_path).ok


def order(**kw):
    base = dict(usd=20.0, equity=1000.0, forecast_ts=NOW - 3600, forecast_mid=0.50, mid_now=0.51, spread=0.02,
                book_ts=NOW - 5, rules_clear=True, hours_to_resolution=200.0, now=NOW)
    base.update(kw)
    return safety.check_order(CFG, **base)


def test_order_checks():
    assert order() == []
    assert "forecast is" in order(forecast_ts=NOW - 7 * 3600)[0]
    assert "snapshot" in order(book_ts=NOW - 600)[0]
    assert "mid moved" in order(mid_now=0.56)[0]
    assert "spread" in order(spread=0.06)[0]
    assert "rules" in order(rules_clear=False)[0]
    assert "rules" in order(rules_clear=None)[0]
    assert "to resolution" in order(hours_to_resolution=3.0)[0]
    assert "ceiling" in order(usd=150.0, equity=100_000.0)[0]
    assert "of equity" in order(usd=50.0)[0]
    assert "two-sided" in order(mid_now=None, spread=None)[0]


# ---- scoring ---------------------------------------------------------------

def test_brier_and_bets_needed():
    assert scoring.brier(0.7, 1) == pytest.approx(0.09)
    assert scoring.log_loss(0.5, 1) == pytest.approx(0.6931, abs=1e-4)
    assert scoring.bets_needed(0.05) == 400
    assert scoring.bets_needed(0.10) == 100
    assert scoring.bets_needed(0.0) > 10 ** 6


def _resolved(ledger, market, i, p, mid, outcome):
    mid_ = f"m{i}"
    ledger.upsert_market({**market, "market_id": mid_, "yes_token": f"{mid_}-y", "no_token": f"{mid_}-n"})
    ledger.add_forecast({"market_id": mid_, "p_yes": p, "market_mid": mid, "ts": 100.0 + i})
    ledger.mark_resolved(mid_, outcome, ts=10_000.0)


def test_brier_vs_market_detects_a_better_forecaster(ledger, market):
    for i in range(40):                       # model at 0.8/0.2, market at 0.6/0.4, model always on the right side
        yes = i % 2 == 0
        _resolved(ledger, market, i, 0.8 if yes else 0.2, 0.6 if yes else 0.4, 1.0 if yes else 0.0)
    rep = scoring.brier_vs_market(ledger)
    assert rep.n == 40
    assert rep.model == pytest.approx(0.04) and rep.market == pytest.approx(0.16)
    assert rep.edge == pytest.approx(0.12)
    assert rep.blend == pytest.approx(0.09)
    assert sum(b["n"] for b in rep.calibration) == 40


def test_brier_verdicts(ledger, market):
    assert "too few" in scoring.brier_vs_market(ledger).verdict()
    for i in range(40):                       # model wrong side half the time by a wide margin
        yes = i % 2 == 0
        good = i % 4 < 2
        p = (0.9 if yes else 0.1) if good else (0.2 if yes else 0.8)
        _resolved(ledger, market, i, p, 0.6 if yes else 0.4, 1.0 if yes else 0.0)
    rep = scoring.brier_vs_market(ledger)
    assert rep.n == 40 and rep.t == rep.t
    assert "WORSE" in rep.verdict() or "no measurable" in rep.verdict()


def test_only_first_forecast_per_market_counts(ledger, market):
    _resolved(ledger, market, 1, 0.8, 0.6, 1.0)
    ledger.add_forecast({"market_id": "m1", "p_yes": 0.1, "market_mid": 0.6, "ts": 500.0})
    assert scoring.brier_vs_market(ledger).n == 1
    assert scoring.brier_vs_market(ledger, first_only=False).n == 2


def test_price_drift(ledger, market):
    ledger.upsert_market(market)
    ledger.add_forecast({"market_id": "m1", "p_yes": 0.70, "market_mid": 0.50, "ts": 1000.0})
    ledger.add_snapshot("m1", 0.59, 0.61, 0.60, ts=1000.0 + 72 * 3600 + 10)
    rep = scoring.price_drift(ledger, horizon_hours=72)
    assert rep.n == 1 and rep.toward == 1 and rep.mean_capture == pytest.approx(0.5)
    # a forecast that agrees with the market is not counted
    ledger.add_forecast({"market_id": "m1", "p_yes": 0.51, "market_mid": 0.50, "ts": 1001.0})
    assert scoring.price_drift(ledger, horizon_hours=72).n == 1


def test_pnl(ledger, market):
    ledger.upsert_market(market)
    ledger.deposit(100.0)
    ledger.apply_fill(None, "m1", "m1-yes", "YES", "BUY", 0.50, 40, fee=0.5)
    ledger.settle("m1", 1.0)
    ledger.record_equity({})
    out = scoring.pnl(ledger)
    assert out["pnl"] == pytest.approx(19.5) and out["fees"] == pytest.approx(0.5)
    assert out["markets_settled"] == 1 and out["settled_wins"] == 1


def test_gates_start_closed_and_open_on_evidence(ledger, market):
    gs = scoring.gates(ledger)
    assert len(gs) == 6 and not any(ok for _, ok, _ in gs)
    ledger.deposit(1000.0)
    week = 7 * 86400.0
    for i in range(210):                       # ten weeks of forecasts the market later moves toward, model right
        yes = i % 2 == 0
        mid_ = f"g{i}"
        ts = 1000.0 + i * (10 * week / 210)
        ledger.upsert_market({**market, "market_id": mid_, "event_id": f"ev{i}", "yes_token": f"{mid_}-y", "no_token": f"{mid_}-n"})
        ledger.add_forecast({"market_id": mid_, "p_yes": 0.7 if yes else 0.3, "market_mid": 0.55 if yes else 0.45, "ts": ts})
        ledger.add_snapshot(mid_, None, None, (0.60 if yes else 0.40) + (0.02 if i % 3 == 0 else 0.0), ts=ts + 72 * 3600 + 5)
        ledger.mark_resolved(mid_, 1.0 if yes else 0.0, ts=ts + 20 * 86400)
    ledger.apply_fill(None, "g0", "g0-y", "YES", "BUY", 0.5, 20)
    ledger.settle("g0", 1.0)
    ledger.record_equity({})
    gs = dict((name, ok) for name, ok, _ in scoring.gates(ledger))
    assert all(gs.values()), gs
