"""One trading cycle. Deterministic code around a single uncertain input, the forecast.

    1. mark      refresh prices of everything held or recently forecast; settle resolved markets;
                 fill or expire resting paper orders
    2. safety    account-level limits (kill switch, drawdown, loss, daily budget)
    3. exits     sell positions whose edge has reversed on a fresh forecast
    4. forecast  filter the venue's markets by rule, then ask Claude about the few that pass
    5. entries   blend each forecast with the market price, size by fractional Kelly under hard caps,
                 run the per-order checks, place the order
    6. record    equity row, run summary, every decision with its reason (including the trades not taken)

A failure in one market never stops the cycle; a failure of the account checks stops all new positions.
"""
from __future__ import annotations

import math
import re
import time
import uuid
from dataclasses import dataclass, field

from . import safety, universe
from .broker import PaperBroker
from .fees import FeeModel
from .forecast import Forecast
from .ledger import Ledger
from .sizing import Exposure, SizingRules, exit_signal, plan_entry
from .venue import Market, brief

DAY = 86400.0


@dataclass
class CycleResult:
    run_id: str
    status: str = "ok"
    log: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def say(self, msg: str) -> None:
        self.log.append(msg)


class Trader:
    def __init__(self, cfg: dict, ledger: Ledger, venue, forecaster, root=".", heartbeat=None):
        self.cfg, self.ledger, self.venue, self.forecaster, self.root = cfg, ledger, venue, forecaster, root
        self.heartbeat = heartbeat or (lambda: None)   # called between slow steps (keeps the run lock fresh)
        self.rules = SizingRules.from_config(cfg.get("sizing"))
        self.fees = FeeModel.from_config(cfg)
        ex = cfg.get("execution") or {}
        self.style = str(ex.get("style", "passive")).lower()
        self.tick = float(ex.get("tick", 0.01))
        self.exit_margin = float(ex.get("exit_margin", 0.03))
        self.track_days = float(ex.get("track_forecasts_days", 7.0))
        self.reentry_cooldown_s = float(ex.get("reentry_cooldown_hours", 72.0)) * 3600.0
        self.max_depth_share = float(ex.get("max_depth_share", 0.25))
        if safety.is_live(cfg):
            safety.require_live_confirmation(cfg)
            raise NotImplementedError("account.mode 'live' is not implemented: see docs/GO_LIVE.md")
        self.broker = PaperBroker(ledger, self.fees, depth_haircut=float(ex.get("depth_haircut", 0.5)),
                                  resting_ttl_hours=float(ex.get("resting_ttl_hours", 24.0)))
        self._books: dict[str, tuple] = {}       # market_id -> (yes Book, no Book, state)
        self._markets: dict[str, Market] = {}

    # ---- helpers ---------------------------------------------------------------
    def _category(self, market_id: str) -> str | None:
        row = self.ledger.market(market_id)
        return row["category"] if row else None

    def _load_books(self, market_id: str, res: CycleResult, snapshot: bool = True):
        if market_id in self._books:
            return self._books[market_id]
        try:
            yes, no, state = self.venue.books(market_id)
        except Exception as e:                                   # one market's failure is not the cycle's
            res.say(f"{market_id}: order book unavailable ({brief(e)})")
            return None
        self._books[market_id] = (yes, no, state)
        if snapshot:
            m = self._markets.get(market_id)
            self.ledger.add_snapshot(market_id, yes.best_bid, yes.best_ask, yes.mid,
                                     m.liquidity if m else None, m.volume if m else None, ts=yes.ts)
        return self._books[market_id]

    def _marks(self) -> dict[str, tuple]:
        """token -> (bid, mid). A position with no book this cycle (its market closed and is waiting to settle, or
        the book request failed) keeps its last recorded price: valuing it at zero would fake a drawdown."""
        marks = {}
        for mid, (yes, no, _) in self._books.items():
            marks[yes.token_id] = (yes.best_bid, yes.mid)
            marks[no.token_id] = (no.best_bid, no.mid)
        for pos in self.ledger.positions():
            if pos["token_id"] in marks:
                continue
            snap = self.ledger.one("SELECT bid, ask, mid FROM snapshots WHERE market_id=? AND mid IS NOT NULL "
                                   "ORDER BY ts DESC LIMIT 1", (pos["market_id"],))
            if not snap:
                continue
            if pos["outcome"] == "YES":
                marks[pos["token_id"]] = (snap["bid"], snap["mid"])
            else:
                marks[pos["token_id"]] = (None if snap["ask"] is None else 1.0 - snap["ask"], 1.0 - snap["mid"])
        return marks

    def _exposure(self, m: Market, equity: float) -> Exposure:
        e = self.ledger.exposure(market_id=m.market_id, event_id=m.event_id, category=m.category)
        cash = self.ledger.cash()
        for o in self.broker.resting():                          # money promised to resting orders is spoken for
            usd = float(o["usd"])
            row = self.ledger.market(o["market_id"])
            e["total"] += usd
            cash -= usd
            if o["market_id"] == m.market_id:
                e["market"] += usd
            if row and m.event_id and row["event_id"] == m.event_id:
                e["event"] += usd
            if row and m.category and row["category"] == m.category:
                e["category"] += usd
        return Exposure(equity=equity, cash=max(cash, 0.0), market=e["market"], event=e["event"],
                        category=e["category"], total=e["total"])

    # ---- 1. mark ------------------------------------------------------------------
    def mark(self, res: CycleResult, now: float) -> None:
        closed: set[str] = set()
        watch = {p["market_id"] for p in self.ledger.positions()} | {o["market_id"] for o in self.broker.resting()}
        recent = {r["market_id"] for r in self.ledger.q(
            "SELECT DISTINCT f.market_id FROM forecasts f JOIN markets m ON m.market_id=f.market_id "
            "WHERE f.ts>=? AND m.payout_yes IS NULL", (now - self.track_days * DAY,))}
        for mid in sorted(watch | recent):
            try:
                m = self.venue.market(mid)
            except Exception as e:
                res.say(f"{mid}: market detail unavailable ({brief(e)})")
                m = None
            if m is not None:
                self._markets[mid] = m
                self.ledger.set_checked(mid, now)
            if m is not None and m.closed:
                closed.add(mid)                                  # its resting orders wait for the settlement
                self._settle(mid, res, now)
                continue
            self._load_books(mid, res)
        self._check_resolutions(watch | recent, res, now)
        books = {}
        for mid, (yes, no, _) in self._books.items():
            books[yes.token_id], books[no.token_id] = yes, no
        for line in self.broker.work_resting(books, self._category, now, closed=closed):
            res.say(line)

    def _check_resolutions(self, already: set[str], res: CycleResult, now: float, limit: int = 40) -> None:
        """Every market that was ever forecast must end up with its outcome recorded, traded or not: the forecast
        scoring is only honest on the full set. Markets no longer tracked each cycle are looked up twice a day
        once their end date is near, and every three days before that (some resolve early)."""
        rows = self.ledger.q(
            """SELECT m.market_id, m.end_ts, COALESCE(m.checked_ts, MAX(f.ts)) AS checked FROM markets m
               JOIN forecasts f ON f.market_id = m.market_id WHERE m.payout_yes IS NULL
               GROUP BY m.market_id ORDER BY checked""")
        done = 0
        for r in rows:
            mid = r["market_id"]
            if mid in already or done >= limit:
                continue
            idle = now - float(r["checked"] or 0.0)
            near_end = r["end_ts"] is not None and now >= float(r["end_ts"]) - DAY
            if not (idle >= 72 * 3600.0 or (near_end and idle >= 12 * 3600.0)):
                continue
            done += 1
            try:
                is_closed = self.venue.is_closed(mid)
            except Exception as e:
                res.say(f"{mid}: resolution check failed ({brief(e)})")
                continue
            self.ledger.set_checked(mid, now)
            if is_closed:
                self._settle(mid, res, now)

    def _settle(self, market_id: str, res: CycleResult, now: float) -> None:
        """Only a market the venue reports as closed is settled, and only at a payout of exactly 0, 0.5 or 1:
        anything else is left for a person to look at."""
        try:
            pay = self.venue.settlement(market_id)
        except Exception as e:
            res.say(f"{market_id}: closed, settlement unavailable ({brief(e)})")
            return
        if pay is None:
            res.say(f"{market_id}: closed, waiting for settlement")
            return
        if pay not in (0.0, 0.5, 1.0):
            res.say(f"{market_id}: settlement value {pay!r} not understood, NOT settled: check by hand")
            return
        for line in self.broker.resolve_closed(market_id, pay, self._category, now):
            res.say(line)
        credited = self.ledger.settle(market_id, pay, ts=now)
        res.say(f"{market_id}: settled, YES pays {pay:g}, ${credited:,.2f} credited")

    # ---- 3. exits -------------------------------------------------------------------
    def exits(self, res: CycleResult, now: float) -> None:
        max_age = safety.settings(self.cfg)["max_forecast_age_hours"] * 3600.0
        for pos in self.ledger.positions():
            mid, side = pos["market_id"], pos["outcome"]
            f = self.ledger.latest_forecast(mid)
            if not f or now - float(f["ts"]) > max_age:
                continue                                         # no fresh view: hold, it gets re-forecast first
            if f["run_id"] == res.run_id:                        # forecast made this cycle: the book read before it is stale
                self._books.pop(mid, None)
            b = self._load_books(mid, res)
            if not b:
                continue
            yes, no, _ = b
            book = yes if side == "YES" else no
            if yes.mid is None:
                continue
            sell, why = exit_signal(side, float(f["p_yes"]), yes.mid, book.best_bid, self.rules, self.exit_margin)
            if not sell:
                continue
            did = self.ledger.add_decision({"ts": now, "run_id": res.run_id, "market_id": mid, "forecast_id": f["id"],
                                            "action": "SELL", "reason": why, "p_model": f["p_yes"], "p_market": yes.mid})
            known = self._markets.get(mid)
            sold = self.broker.sell_taker(res.run_id, mid, side, book, float(pos["shares"]), limit=book.best_bid - 0.02,
                                          category=self._category(mid), decision_id=did, now=now,
                                          fee_rate=known.fee_rate if known else None)
            res.say(f"{mid}: SELL {sold:g} {side} ({why})")
            res.stats["exits"] = res.stats.get("exits", 0) + 1

    # ---- 4. forecast ------------------------------------------------------------------
    def forecast(self, res: CycleResult, now: float) -> list[tuple[Market, Forecast, int, float]]:
        """Returns (market, forecast, forecast row id, market mid when the forecast was requested)."""
        st = universe.settings(self.cfg)
        try:
            listed = self.venue.list_markets(max_events=int(st["max_events_scanned"]),
                                             categories=list(st["categories_allow"]) or None,
                                             min_days=float(st["min_days_to_resolution"]),
                                             max_days=float(st["max_days_to_resolution"]))
        except Exception as e:
            res.say(f"market listing failed ({brief(e)}): no new forecasts this cycle")
            return []
        for m in listed:
            m.raw["lite"] = True                                 # listing rows may lack the rules text
        held = {p["market_id"] for p in self.ledger.positions()} | {o["market_id"] for o in self.broker.resting()}
        last = {r["market_id"]: float(r["ts"]) for r in self.ledger.q("SELECT market_id, MAX(ts) AS ts FROM forecasts GROUP BY market_id")}
        candidates, dropped = universe.choose(listed, self.cfg, last, held, now)
        res.stats.update(listed=len(listed), passed_listing=len(candidates))
        # Read the order book of every candidate (one request each), then spend the few forecasts on the best:
        # held markets first, then markets deep enough to trade, then the rest (forecast and scored, not traded).
        ranked = []
        for m in candidates[:int(st["max_books_per_cycle"])]:
            is_held = m.market_id in held
            if getattr(self.venue, "rate_limited", 0) >= 3 and not is_held:
                res.say("the exchange is rate limiting: no more order books this cycle")
                break
            b = self._load_books(m.market_id, res)
            if b is None:
                continue
            why = "" if is_held else universe.book_check(b[0], b[2], st)
            thin = "" if is_held else universe.trade_check(b[0], st) if not why else ""
            if not why and thin and not st["forecast_untradable"]:
                why = thin
            if why:
                dropped[m.market_id] = why
                continue
            ranked.append((0 if is_held else 1, 1 if thin else 0, 0 if m.market_id not in last else 1,
                           -b[0].near_touch_usd(st["depth_band"]), m.market_id, m))
        ranked.sort(key=lambda r: r[:5])
        res.stats.update(candidates_with_books=len(ranked), tradable=sum(1 for r in ranked if r[1] == 0 and r[0] == 1))

        out, asked = [], 0
        for *_, m in ranked:
            if asked >= int(st["max_candidates_per_cycle"]):   # attempts, not successes: a forecaster that is
                break                                            # down must not be called once per listed market
            is_held = m.market_id in held
            b = self._books.get(m.market_id)
            try:
                full = self.venue.enrich(m) or m                 # rules text and current status
            except Exception as e:
                res.say(f"{m.market_id}: detail unavailable ({type(e).__name__})")
                continue
            self._markets[m.market_id] = full
            if full.closed:
                dropped[m.market_id] = "closed"
                continue
            why = "" if is_held else universe.prefilter(full, st, now)
            if why:
                dropped[m.market_id] = why
                continue
            # The benchmark price is read immediately before the forecast is requested: earlier forecasts in this
            # cycle took minutes, and a price from before them would not be the price this forecast competes with.
            if asked:
                self._books.pop(m.market_id, None)
                b = self._load_books(m.market_id, res)
            if b is None or b[0].mid is None:
                dropped[m.market_id] = "no two-sided market"
                res.say(f"{m.market_id}: not forecast (no two-sided market)")
                continue
            mid_then = b[0].mid
            self.ledger.upsert_market(full.ledger_row(), ts=now)
            asked += 1
            try:
                f = self.forecaster.forecast(full, now)
            except Exception as e:
                res.say(f"{m.market_id}: forecaster failed ({brief(e)})")
                continue
            finally:
                self.heartbeat()
            if f is None:
                why_not = getattr(self.forecaster, "last_error", "") or "no answer yet"
                res.say(f"{m.market_id}: no usable forecast ({why_not})")
                continue
            fid = self.ledger.add_forecast(f.ledger_row(res.run_id, mid_then))
            res.say(f"{m.market_id}: forecast {f.p_yes:.2f} vs market {mid_then:.2f} ({f.confidence}, runs {f.p_runs})")
            out.append((full, f, fid, mid_then))
        res.stats.update(forecasts=len(out), dropped=len(dropped))
        counts: dict[str, int] = {}
        for why in dropped.values():
            key = re.sub(r"[-+]?\$?\d[\d,.]*", "N", why)[:60]
            counts[key] = counts.get(key, 0) + 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:6]
        res.say(f"{len(listed)} markets listed, {len(candidates)} passed the listing filters, {len(ranked)} have a usable "
                f"order book ({res.stats['tradable']} deep enough to trade), {asked} sent to the forecaster; "
                f"not considered: " + "; ".join(f"{n} {why}" for why, n in top))
        return out

    # ---- 5. entries ----------------------------------------------------------------------
    def _entry_prices(self, yes, no, m: Market) -> tuple[float | None, float | None, float, float]:
        """Price to pay for each side and the fee per share at that price. The market's own tick size and fee
        coefficient are used when the exchange gives them; the config values are the fallback."""
        tick = m.tick or self.tick
        if self.style == "taker":
            ay, an = yes.best_ask, no.best_ask
            fee = lambda p: self.fees.per_share(p, m.category, market_rate=m.fee_rate) if p else 0.0
            return ay, an, fee(ay), fee(an)

        def passive(book):                          # one tick inside the bid, never touching the ask
            if book.best_bid is None or book.best_ask is None:
                return None
            p = book.best_bid + tick if book.spread >= 2 * tick - 1e-9 else book.best_bid
            return round(min(p, book.best_ask - tick), 4)
        py, pn = passive(yes), passive(no)
        maker = m.maker_fee_rate if m.maker_fee_rate is not None else self.fees.maker_rate
        mfee = lambda p: maker * p * (1.0 - p) if p else 0.0      # some venues charge resting orders a little
        return py, pn, mfee(py), mfee(pn)

    def entries(self, forecasts: list[tuple[Market, Forecast, int, float]], equity: float, acct: safety.AccountCheck,
                res: CycleResult, now: float) -> None:
        orders_left, usd_left = acct.orders_left, acct.usd_left
        for m, f, fid, mid_then in forecasts:
            # A forecast takes minutes. Read the book again: the order is priced on the market as it is NOW, and a
            # move since the forecast was requested means news the forecast may not contain.
            self._books.pop(m.market_id, None)
            b = self._load_books(m.market_id, res)
            base = {"ts": now, "run_id": res.run_id, "market_id": m.market_id, "forecast_id": fid, "p_model": f.p_yes,
                    "p_market": b[0].mid if b else mid_then}

            def skip(reason: str, **extra):
                self.ledger.add_decision({**base, "action": "SKIP", "reason": reason, **extra})
                res.say(f"{m.market_id}: no trade ({reason})")

            for o in self.broker.resting(m.market_id):           # a new forecast replaces any working order,
                self.broker.cancel(o["id"], "replaced by a newer forecast")   # whatever the new forecast says
            ks = safety.kill_switch_on(self.cfg, self.root)      # checked again: forecasting took minutes
            if ks:
                skip(f"kill switch {ks} appeared during the cycle")
                res.status = "stopped"
                continue
            if b is None or b[0].mid is None:
                skip("no two-sided market after the forecast")
                continue
            yes, no, _ = b
            if f.confidence == "low":
                skip("forecast confidence is low")
                continue
            if f.flags and (self.cfg.get("forecaster") or {}).get("flags_block", True):
                skip("forecaster raised flags: " + "; ".join(f.flags)[:300])
                continue
            held = [self.ledger.position(t) for t in (m.yes_token, m.no_token)]
            if any(p is not None and p["shares"] > 1e-6 for p in held):
                skip("already held: positions are not added to")
                continue
            sold = self.ledger.one("SELECT MAX(ts) AS ts FROM fills WHERE market_id=? AND side='SELL'", (m.market_id,))
            if sold and sold["ts"] is not None and now - float(sold["ts"]) < self.reentry_cooldown_s:
                skip("sold recently: no re-entry (and no flip to the other side) during the cooldown")
                continue
            if orders_left <= 0 or usd_left < self.rules.min_order_usd:
                skip("daily order budget used")
                continue

            thin = universe.trade_check(yes, universe.settings(self.cfg))
            if thin:
                skip(f"forecast only, not traded: {thin}")
                continue
            py, pn, fy, fn = self._entry_prices(yes, no, m)
            sz = plan_entry(f.p_yes, yes.mid, py, pn, self._exposure(m, equity), self.rules,
                            days_to_resolution=m.days_to_end(now), fee_yes=fy, fee_no=fn)
            detail = {"side": sz.side, "kelly_full": sz.kelly_full, "binding": sz.binding, "limit": sz.limit_price,
                      "style": self.style, "mid_at_forecast": mid_then}
            if not sz.trade:
                skip(sz.reason, q=sz.q, cost=sz.cost, edge=sz.edge, detail=detail)
                continue
            # never more than a share of what is resting near the price: a bigger order would BE the market
            room = self.max_depth_share * yes.near_touch_usd(universe.settings(self.cfg)["depth_band"])
            stake = round(min(sz.stake, usd_left, room), 2)
            if stake < self.rules.min_order_usd:
                skip(f"only ${room:.2f} of depth to trade against (minimum order ${self.rules.min_order_usd:.2f})",
                     q=sz.q, cost=sz.cost, edge=sz.edge, detail=detail)
                continue
            days = m.days_to_end(now)
            problems = safety.check_order(self.cfg, usd=stake, equity=equity, forecast_ts=f.ts, forecast_mid=mid_then,
                                          mid_now=yes.mid, spread=yes.spread, book_ts=yes.ts, rules_clear=f.rules_clear,
                                          hours_to_resolution=None if days is None else days * 24.0, now=max(now, yes.ts))
            if problems:
                skip("; ".join(problems), q=sz.q, cost=sz.cost, edge=sz.edge, detail=detail)
                continue
            book = yes if sz.side == "YES" else no
            if m.min_qty and stake / max(sz.cost, 1e-9) < m.min_qty:
                skip(f"stake ${stake:.2f} buys fewer than the market's minimum of {m.min_qty:g} contracts",
                     q=sz.q, cost=sz.cost, edge=sz.edge, detail=detail)
                continue
            did = self.ledger.add_decision({**base, "action": f"BUY_{sz.side}", "reason": sz.reason, "q": sz.q,
                                            "cost": sz.cost, "edge": sz.edge, "stake": stake, "detail": detail})
            if self.style == "taker":
                spent = self.broker.buy_taker(res.run_id, m.market_id, sz.side, book, stake, sz.limit_price,
                                              category=m.category, decision_id=did, now=now, fee_rate=m.fee_rate)
                res.say(f"{m.market_id}: BUY {sz.side} ${spent:,.2f} taken ({sz.reason})")
            else:
                tick = m.tick or self.tick
                quote = py if sz.side == "YES" else pn                                   # the passive price, before fees
                price = min(quote, math.floor(sz.limit_price / tick + 1e-9) * tick)     # on the market's price grid
                price = round(price, 4)
                self.broker.place_resting(res.run_id, m.market_id, sz.side, book.token_id, price, stake, decision_id=did, now=now)
                spent = stake
                res.say(f"{m.market_id}: resting BUY {sz.side} ${stake:,.2f} @ {price:.3f} ({sz.reason})")
            orders_left -= 1
            usd_left -= spent
            res.stats["orders"] = res.stats.get("orders", 0) + 1

    # ---- the cycle ------------------------------------------------------------------------
    def run(self, now: float | None = None, do_forecast: bool = True) -> CycleResult:
        now = now or time.time()
        res = CycleResult(run_id=time.strftime("%Y%m%d-%H%M%S", time.gmtime(now)) + "-" + uuid.uuid4().hex[:6])
        self.ledger.start_run(res.run_id)
        try:
            prev = self.ledger.last_equity()
            ks = safety.kill_switch_on(self.cfg, self.root)
            if ks:                                               # before mark(): a stopped account fills nothing
                for o in self.broker.resting():
                    self.broker.cancel(o["id"], f"kill switch {ks}")
            self.mark(res, now)
            eq = self.ledger.record_equity(self._marks(), ts=now)
            n24, usd24 = self.ledger.count_orders_since(now - DAY)
            resting_usd = sum(float(o["usd"]) for o in self.broker.resting())
            acct = safety.check_account(self.cfg, equity=eq["equity"], prev_equity=float(prev["equity"]) if prev else None,
                                        high_water=self.ledger.high_water(), deposited=self.ledger.deposits(),
                                        orders_24h=n24 + len(self.broker.resting()), deployed_24h=usd24 + resting_usd,
                                        root=self.root)
            res.say(acct.summary())
            # Forecasts first (held markets are re-forecast before anything new), so exits act on a fresh view.
            forecasts = self.forecast(res, now) if acct.ok and do_forecast else []
            if acct.exits_ok:
                self.exits(res, now)
            if acct.ok:
                self.entries(forecasts, eq["equity"], acct, res, now)
            else:
                res.status = "stopped"
            if res.status == "stopped":
                for o in self.broker.resting():
                    self.broker.cancel(o["id"], "account safety stop")
            eq = self.ledger.record_equity(self._marks(), ts=now + 1e-3)
            res.stats.update(equity=eq["equity"], cash=eq["cash"], positions=eq["n_positions"],
                             resting=len(self.broker.resting()), venue_requests=getattr(self.venue, "requests", None))
        except Exception as e:
            res.status = "error"
            res.say(f"cycle failed: {brief(e)}")
            self.ledger.finish_run(res.run_id, res.status, {"log": res.log, **res.stats})
            raise
        self.ledger.finish_run(res.run_id, res.status, {"log": res.log, **res.stats})
        return res
