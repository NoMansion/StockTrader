import json
from datetime import date

from src import discord_report as rep


def F(sym, side, qty, d, price=10.0):
    return {"symbol": sym, "side": side, "qty": str(qty), "price": str(price), "date": d}


def test_period_returns_windows_and_short_history():
    s = [(date(2026, 11, 5), 100.0), (date(2026, 11, 10), 101.0), (date(2026, 11, 16), 102.0), (date(2026, 11, 17), 99.0)]
    r = {x["label"]: x for x in rep.period_returns(s, date(2026, 11, 17))}
    assert abs(r["Day"]["pct"] - (99 / 102 - 1)) < 1e-12 and r["Day"]["since"] is None
    assert abs(r["Week"]["pct"] - (99 / 101 - 1)) < 1e-12 and r["Week"]["since"] is None   # last close on/before 11-10
    assert r["Month"]["since"] == date(2026, 11, 5) and abs(r["Month"]["pct"] + 0.01) < 1e-12   # account younger
    assert abs(r["All time"]["dollars"] + 1.0) < 1e-12 and r["All time"]["since"] is None


def test_ytd_uses_last_close_of_previous_year():
    s = [(date(2025, 12, 30), 100.0), (date(2025, 12, 31), 110.0), (date(2026, 1, 2), 121.0)]
    r = {x["label"]: x for x in rep.period_returns(s, date(2026, 1, 2))}
    assert abs(r["YTD"]["pct"] - 0.10) < 1e-12 and abs(r["All time"]["pct"] - 0.21) < 1e-12


def test_months_back_clamps_day():
    assert rep._months_back(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert rep._months_back(date(2026, 1, 15), 12) == date(2025, 1, 15)


def test_trades_today_classifies():
    d = date(2026, 11, 17)
    today = [F("NEW", "buy", 5, d), F("ADD", "buy", 2, d), F("TRIM", "sell", 1, d), F("OUT", "sell", 3, d)]
    qty_now = {"NEW": 5, "ADD": 7, "TRIM": 4}
    t = rep.trades_today(today, qty_now, {k: 10.0 for k in qty_now})
    assert [s for s, _ in t["new"]] == ["NEW"] and [s for s, _ in t["added"]] == ["ADD"]
    assert [s for s, _ in t["trimmed"]] == ["TRIM"] and [s for s, _ in t["exited"]] == ["OUT"]
    assert t["new"][0][1] == 50.0


def test_estimated_dividends_use_shares_before_ex_date():
    fills = [F("A", "buy", 10, date(2026, 11, 9)), F("A", "sell", 4, date(2026, 11, 12)),
             F("B", "buy", 5, date(2026, 11, 13))]
    divs = [{"symbol": "A", "ex_date": date(2026, 11, 12), "rate": 1.0, "payable_date": None},   # 10 held the night before
            {"symbol": "A", "ex_date": date(2026, 11, 13), "rate": 1.0, "payable_date": None},   # 6 held
            {"symbol": "B", "ex_date": date(2026, 11, 13), "rate": 1.0, "payable_date": None},   # bought on the ex-date: 0
            {"symbol": "A", "ex_date": date(2026, 12, 1), "rate": 1.0, "payable_date": None}]    # future: not yet
    est = rep.estimated_dividends(fills, divs, date(2026, 11, 17))
    assert [e["amount"] for e in est] == [10.0, 6.0]
    cum = rep.cumulative_by_date(est, "ex_date", [date(2026, 11, 11), date(2026, 11, 12), date(2026, 11, 17)])
    assert cum == [0.0, 10.0, 16.0]
    assert rep.dividends_in_window(est, "ex_date", date(2026, 11, 12), date(2026, 11, 17)) == 6.0


def _ctx(n_pos=60):
    pos = [{"symbol": "IEF", "qty": 500, "value": 50_000.0, "day_pct": 0.003, "total_pct": -0.001, "day_pl": 150.0}]
    pos += [{"symbol": f"S{i:02d}", "qty": 10, "value": 700.0 - i, "day_pct": 0.01, "total_pct": -0.02, "day_pl": 7.0}
            for i in range(n_pos)]
    pos += [{"symbol": "DUST", "qty": 0.1, "value": 2.0, "day_pct": 0.0, "total_pct": 0.0, "day_pl": 0.0}]
    trades = {"new": [(f"N{i}", 100.0) for i in range(120)], "added": [], "trimmed": [("GLD", 19_000.0)], "exited": []}
    return {"today": date(2026, 11, 17), "paper": True, "equity": 97_000.0, "cash": 1_300.0,
            "returns": rep.period_returns([(date(2026, 11, 5), 100_000.0), (date(2026, 11, 17), 97_000.0)], date(2026, 11, 17)),
            "div_mode": "estimated", "div_total": 27.98, "div_windows": {"Week": 27.98}, "positions": pos,
            "trades": trades, "queued": {"buys": 30, "sells": 44, "buy_v": 9_000.0, "sell_v": 12_000.0,
                                         "new_names": ["N1"], "exit_names": ["S01"]}}


def _full_ctx():
    ctx = _ctx()
    ctx["curve"] = [(date(2026, 11, 5), 100_000.0), (date(2026, 11, 10), 99_000.0), (date(2026, 11, 17), 97_000.0)]
    ctx["spy"] = [(date(2026, 11, 5), 700.0), (date(2026, 11, 10), 710.0), (date(2026, 11, 17), 705.0)]
    ctx["history"] = rep.daily_history(ctx["curve"], ctx["spy"], [F("N1", "buy", 1, date(2026, 11, 17))])
    ctx["sectors"] = {"S00": "Energy"}
    ctx["div_items"] = [{"symbol": "S00", "ex_date": date(2026, 11, 12), "rate": 1.0, "shares": 27.98, "amount": 27.98}]
    ctx["updated"] = "Nov 17, 6:20 PM CT"
    return ctx


def test_embed_has_the_numbers_and_fits_discord_limits():
    ctx = _ctx()
    ctx["trades"] = {"new": [("N1", 100.0), ("N2", 50.0)], "added": [("IEF", 900.0)], "trimmed": [("GLD", 800.0)],
                     "exited": [("S01", 300.0)]}
    e = rep.embed(ctx, "https://example.invalid/", "dashboard.png")
    text = json.dumps(e, ensure_ascii=False)
    for s in ["$97,000.00", "Week", "YTD", "All time", "-3.00%", "since Nov 5", "Bought **3** (2 new)",
              "Sold **2** (1 sold out)", "**30** buys", "$27.98", "attachment://dashboard.png", "https://example.invalid/"]:
        assert s in text, s
    assert e["color"] == rep.NEG_COLOR and len(e["fields"]) <= 25 and len(text) < 6000
    assert all(len(f["value"]) <= 1024 and f["inline"] for f in e["fields"])


def test_daily_history_counts_names_and_spy():
    h = rep.daily_history([(date(2026, 11, 5), 100.0), (date(2026, 11, 6), 101.0)],
                          [(date(2026, 11, 5), 10.0), (date(2026, 11, 6), 10.5)],
                          [F("A", "buy", 1, date(2026, 11, 6)), F("A", "buy", 1, date(2026, 11, 6)), F("B", "sell", 1, date(2026, 11, 6))])
    assert len(h) == 1 and abs(h[0]["day"] - 0.01) < 1e-12 and abs(h[0]["spy"] - 0.05) < 1e-12
    assert h[0]["buys"] == 1 and h[0]["sells"] == 1


def test_dashboard_renders_as_png():
    from src import report_images
    b = report_images.dashboard(_full_ctx())
    assert b[1:4] == b"PNG" and 10_000 < len(b) < 2_000_000


def test_public_page_has_no_dollar_amounts():
    from src import report_site
    page = report_site.build_html(_full_ctx())
    data = page[page.index('id="data">'):page.index("</script>", page.index('id="data">'))]
    assert "$" not in data                      # the page data holds only percentages and weights
    assert "97,000" not in page and "97000" not in page and "27.98" not in page
    assert '"s":"S00"' in data and '"sector":"Energy"' in data and "noindex" in page


def test_money_and_pct():
    assert rep.money(-1234.5) == "-$1,234.50" and rep.money(5, sign=True) == "+$5.00" and rep.pct(-0.0034) == "-0.34%"


def test_deposit_is_not_a_gain():
    d = [date(2026, 12, i) for i in (1, 2, 3, 4)]
    # 15,000 start, +1% on day 2, a 1,000 deposit on day 3 with a flat market, -1% on day 4
    v = [15_000.0, 15_150.0, 16_150.0, 15_988.5]
    flows = {d[2]: 1_000.0}
    r = {x["label"]: x for x in rep.period_returns(list(zip(d, v)), d[3], flows)}
    assert abs(r["Day"]["pct"] + 0.01) < 1e-9
    assert abs(r["All time"]["pct"] - (1.01 * 1.0 * 0.99 - 1)) < 1e-9       # deposit day counts as 0%, not +6.6%
    assert abs(r["All time"]["dollars"] - (15_988.5 - 15_000 - 1_000)) < 1e-9
    g = dict(rep.growth_index(list(zip(d, v)), flows))
    assert abs(g[d[2]] - g[d[1]]) < 1e-9


def test_withdrawal_is_not_a_loss_and_late_booking_nets_out():
    d = [date(2026, 12, i) for i in (1, 2, 3)]
    v = [20_000.0, 19_000.0, 19_000.0]        # 1,000 withdrawn on day 2, booked by the history on day 3
    g = dict(rep.growth_index(list(zip(d, v)), {d[2]: -1_000.0}))
    assert abs(g[d[2]] / g[d[0]] - 1.0) < 1e-9   # the two days net out: no loss over the period


def test_external_flows_skip_initial_funding_fees_and_dividends():
    d = [date(2026, 11, i) for i in (5, 6, 9, 20)]
    cf = {"JNLC": [0.0, 100_000.0, 0.0, 0.0], "CSD": [0.0, 0.0, 0.0, 2_500.0], "CSW": [0.0, 0.0, 0.0, -500.0],
          "FEE": [0.0, -0.2, -0.1, -0.3], "DIV": [0.0, 0.0, 12.0, 0.0]}
    f = rep.external_flows(cf, d, first_trade=date(2026, 11, 9))
    assert f == {date(2026, 11, 20): 2_000.0}
    assert rep.external_flows(cf, d, first_trade=None) == {date(2026, 11, 6): 100_000.0, date(2026, 11, 20): 2_000.0}


def test_embed_mentions_deposits():
    ctx = _ctx()
    ctx["flows"] = {date(2026, 11, 12): 1_000.0}
    assert "$1,000.00 net deposited" in rep.embed(ctx)["footer"]["text"]


def test_fill_cache_is_per_account(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, "scripts")
    import discord_report as script
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(script, "CACHE", tmp_path / "data" / "discord_fills_cache.json")
    script.CACHE.write_text(json.dumps([{"id": "p1", "symbol": "A", "side": "buy", "qty": "1", "price": "1", "time": "t"}]))
    assert len(script.read_cache("live-id", paper=False)) == 0        # live never adopts the untagged paper cache
    assert len(script.read_cache("paper-id", paper=True)) == 1
    script.cache_path("paper-id").write_text(json.dumps({"account": "paper-id", "fills": [{"id": "x"}]}))
    assert script.read_cache("paper-id", paper=True) == [{"id": "x"}]
    script.cache_path("other").write_text(json.dumps({"account": "someone-else", "fills": [{"id": "y"}]}))
    assert script.read_cache("other", paper=False) == []


def test_page_lists_every_position_including_leftovers():
    from src import report_site
    d = report_site.page_data(_full_ctx())
    syms = [h["s"] for h in d["holdings"]]
    assert "DUST" in syms and len(syms) == len(_full_ctx()["positions"])
    assert d["dust"]["n"] == 1
