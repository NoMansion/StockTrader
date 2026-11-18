"""The account's memory: one SQLite file (data/pmt.db) holding markets seen, price snapshots, every forecast,
every decision (including the trades not taken), orders, fills, positions and the equity curve.

Nothing is ever deleted: the forecast log is the experiment's main result. Whether the account made money over a
few dozen bets is mostly luck; whether the forecasts beat the market's own prices is measurable much sooner.

Cash and positions for the PAPER account live here. For a live account the venue is the source of truth and this
file is the audit log that gets reconciled against it.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS markets (
    market_id TEXT PRIMARY KEY, condition_id TEXT, slug TEXT, question TEXT, rules TEXT,
    event_id TEXT, event_title TEXT, category TEXT, end_ts REAL, neg_risk INTEGER DEFAULT 0,
    yes_token TEXT, no_token TEXT, first_seen REAL, last_seen REAL,
    closed INTEGER DEFAULT 0, resolved_ts REAL, payout_yes REAL,         -- 1, 0 or 0.5 once resolved
    checked_ts REAL                                                      -- last time resolution was looked up
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY, ts REAL, market_id TEXT, bid REAL, ask REAL, mid REAL,
    liquidity REAL, volume24h REAL
);
CREATE INDEX IF NOT EXISTS snapshots_market ON snapshots (market_id, ts);
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY, ts REAL, run_id TEXT, market_id TEXT, backend TEXT, model TEXT,
    p_yes REAL,                -- aggregated model probability
    p_runs TEXT,               -- JSON list of the individual runs
    confidence TEXT, rules_clear INTEGER, flags TEXT, rationale TEXT, sources TEXT,
    market_mid REAL,           -- market mid when the forecast was made (the benchmark to beat)
    cost_usd REAL
);
CREATE INDEX IF NOT EXISTS forecasts_market ON forecasts (market_id, ts);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY, ts REAL, run_id TEXT, market_id TEXT, forecast_id INTEGER,
    action TEXT,               -- BUY_YES, BUY_NO, SELL, HOLD, SKIP
    reason TEXT, p_model REAL, p_market REAL, q REAL, cost REAL, edge REAL, stake REAL, detail TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY, ts REAL, run_id TEXT, mode TEXT, market_id TEXT, token_id TEXT, outcome TEXT,
    side TEXT,                 -- BUY or SELL
    limit_price REAL, usd REAL, shares REAL, status TEXT, venue_order_id TEXT, decision_id INTEGER, note TEXT
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY, ts REAL, order_id INTEGER, market_id TEXT, token_id TEXT, outcome TEXT,
    side TEXT, price REAL, shares REAL, fee REAL
);
CREATE TABLE IF NOT EXISTS positions (
    token_id TEXT PRIMARY KEY, market_id TEXT, outcome TEXT, shares REAL, cost REAL,   -- cost includes fees
    opened_ts REAL, updated_ts REAL
);
CREATE TABLE IF NOT EXISTS cash (id INTEGER PRIMARY KEY, ts REAL, delta REAL, balance REAL, why TEXT);
CREATE TABLE IF NOT EXISTS equity (
    ts REAL PRIMARY KEY, cash REAL, positions_bid REAL, positions_mid REAL, equity REAL, n_positions INTEGER
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started REAL, finished REAL, status TEXT, summary TEXT
);
"""


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def tx(self):
        """All-or-nothing group of writes: a crash in the middle of a fill cannot leave cash and positions apart."""
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    # ---- small helpers -------------------------------------------------
    def q(self, sql: str, args=()) -> list[sqlite3.Row]:
        return self.db.execute(sql, args).fetchall()

    def one(self, sql: str, args=()):
        return self.db.execute(sql, args).fetchone()

    def get_meta(self, key: str, default=None):
        r = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(r["value"]) if r else default

    def set_meta(self, key: str, value) -> None:
        self.db.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value)))
        self.db.commit()

    # ---- cash ----------------------------------------------------------
    def cash(self) -> float:
        r = self.one("SELECT balance FROM cash ORDER BY id DESC LIMIT 1")
        return float(r["balance"]) if r else 0.0

    def _move_cash(self, delta: float, why: str, ts: float | None = None) -> float:
        bal = round(self.cash() + delta, 6)
        self.db.execute("INSERT INTO cash (ts, delta, balance, why) VALUES (?, ?, ?, ?)",
                        (ts or time.time(), delta, bal, why))
        return bal

    def deposit(self, usd: float, why: str = "deposit") -> float:
        with self.tx():
            return self._move_cash(float(usd), why)

    # ---- markets and prices ---------------------------------------------
    def upsert_market(self, m: dict, ts: float | None = None) -> None:
        ts = ts or time.time()
        self.db.execute(
            """INSERT INTO markets (market_id, condition_id, slug, question, rules, event_id, event_title, category,
                                    end_ts, neg_risk, yes_token, no_token, first_seen, last_seen)
               VALUES (:market_id, :condition_id, :slug, :question, :rules, :event_id, :event_title, :category,
                       :end_ts, :neg_risk, :yes_token, :no_token, :ts, :ts)
               ON CONFLICT(market_id) DO UPDATE SET question=excluded.question, rules=excluded.rules,
                   event_id=excluded.event_id, event_title=excluded.event_title, category=excluded.category,
                   end_ts=excluded.end_ts, neg_risk=excluded.neg_risk, yes_token=excluded.yes_token,
                   no_token=excluded.no_token, last_seen=excluded.last_seen""",
            {"condition_id": None, "slug": None, "rules": None, "event_id": None, "event_title": None,
             "category": None, "end_ts": None, "neg_risk": 0, "yes_token": None, "no_token": None, **m, "ts": ts})
        self.db.commit()

    def market(self, market_id: str):
        return self.one("SELECT * FROM markets WHERE market_id=?", (market_id,))

    def add_snapshot(self, market_id: str, bid, ask, mid, liquidity=None, volume24h=None, ts: float | None = None) -> None:
        self.db.execute("INSERT INTO snapshots (ts, market_id, bid, ask, mid, liquidity, volume24h) VALUES (?,?,?,?,?,?,?)",
                        (ts or time.time(), market_id, bid, ask, mid, liquidity, volume24h))
        self.db.commit()

    def last_snapshot(self, market_id: str, before: float | None = None):
        if before is None:
            return self.one("SELECT * FROM snapshots WHERE market_id=? ORDER BY ts DESC LIMIT 1", (market_id,))
        return self.one("SELECT * FROM snapshots WHERE market_id=? AND ts<=? ORDER BY ts DESC LIMIT 1", (market_id, before))

    def set_checked(self, market_id: str, ts: float) -> None:
        self.db.execute("UPDATE markets SET checked_ts=? WHERE market_id=?", (ts, market_id))
        self.db.commit()

    def mark_resolved(self, market_id: str, payout_yes: float, ts: float | None = None) -> None:
        self.db.execute("UPDATE markets SET closed=1, resolved_ts=?, payout_yes=? WHERE market_id=?",
                        (ts or time.time(), float(payout_yes), market_id))
        self.db.commit()

    # ---- forecasts and decisions ----------------------------------------
    def add_forecast(self, f: dict) -> int:
        cur = self.db.execute(
            """INSERT INTO forecasts (ts, run_id, market_id, backend, model, p_yes, p_runs, confidence, rules_clear,
                                      flags, rationale, sources, market_mid, cost_usd)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f.get("ts") or time.time(), f.get("run_id"), f["market_id"], f.get("backend"), f.get("model"),
             float(f["p_yes"]), json.dumps(f.get("p_runs") or []), f.get("confidence"),
             None if f.get("rules_clear") is None else int(bool(f["rules_clear"])),
             json.dumps(f.get("flags") or []), f.get("rationale"), json.dumps(f.get("sources") or []),
             f.get("market_mid"), f.get("cost_usd")))
        self.db.commit()
        return int(cur.lastrowid)

    def latest_forecast(self, market_id: str):
        return self.one("SELECT * FROM forecasts WHERE market_id=? ORDER BY ts DESC LIMIT 1", (market_id,))

    def add_decision(self, d: dict) -> int:
        cur = self.db.execute(
            """INSERT INTO decisions (ts, run_id, market_id, forecast_id, action, reason, p_model, p_market, q, cost,
                                      edge, stake, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d.get("ts") or time.time(), d.get("run_id"), d["market_id"], d.get("forecast_id"), d["action"],
             d.get("reason"), d.get("p_model"), d.get("p_market"), d.get("q"), d.get("cost"), d.get("edge"),
             d.get("stake"), json.dumps(d.get("detail") or {})))
        self.db.commit()
        return int(cur.lastrowid)

    # ---- orders, fills, positions ----------------------------------------
    def add_order(self, o: dict) -> int:
        cur = self.db.execute(
            """INSERT INTO orders (ts, run_id, mode, market_id, token_id, outcome, side, limit_price, usd, shares,
                                   status, venue_order_id, decision_id, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (o.get("ts") or time.time(), o.get("run_id"), o.get("mode", "paper"), o["market_id"], o["token_id"],
             o["outcome"], o["side"], o.get("limit_price"), o.get("usd"), o.get("shares"), o.get("status", "new"),
             o.get("venue_order_id"), o.get("decision_id"), o.get("note")))
        self.db.commit()
        return int(cur.lastrowid)

    def set_order_status(self, order_id: int, status: str, note: str | None = None) -> None:
        self.db.execute("UPDATE orders SET status=?, note=COALESCE(?, note) WHERE id=?", (status, note, order_id))
        self.db.commit()

    def position(self, token_id: str):
        return self.one("SELECT * FROM positions WHERE token_id=?", (token_id,))

    def positions(self) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM positions WHERE shares > 0.000001 ORDER BY opened_ts")

    def apply_fill(self, order_id: int | None, market_id: str, token_id: str, outcome: str, side: str,
                   price: float, shares: float, fee: float = 0.0, ts: float | None = None,
                   order_status: str | None = None, order_note: str | None = None) -> None:
        """Record a fill and move cash and the position together. BUY adds shares at cost price*shares + fee;
        SELL removes shares, credits price*shares - fee and releases cost in proportion. `order_status` updates
        the order in the same transaction, so a crash cannot leave a filled order looking unfilled."""
        ts = ts or time.time()
        side = side.upper()
        with self.tx():
            self.db.execute("INSERT INTO fills (ts, order_id, market_id, token_id, outcome, side, price, shares, fee) "
                            "VALUES (?,?,?,?,?,?,?,?,?)", (ts, order_id, market_id, token_id, outcome, side, price, shares, fee))
            pos = self.position(token_id)
            have, cost = (float(pos["shares"]), float(pos["cost"])) if pos else (0.0, 0.0)
            if side == "BUY":
                spend = price * shares + fee
                if spend > self.cash() + 1e-6:
                    raise ValueError(f"fill needs ${spend:.2f} but cash is ${self.cash():.2f}")
                self._move_cash(-spend, f"buy {outcome} {market_id}", ts)
                have, cost = have + shares, cost + spend
            elif side == "SELL":
                if shares > have + 1e-6:
                    raise ValueError(f"selling {shares} shares but only {have} held")
                self._move_cash(price * shares - fee, f"sell {outcome} {market_id}", ts)
                cost = cost * max(have - shares, 0.0) / have if have > 0 else 0.0
                have = max(have - shares, 0.0)
                if have < 0.005:                                 # under half a cent of a share is rounding, not a position
                    have, cost = 0.0, 0.0
            else:
                raise ValueError(f"unknown side {side!r}")
            if order_status is not None and order_id is not None:
                self.db.execute("UPDATE orders SET status=?, note=COALESCE(?, note) WHERE id=?",
                                (order_status, order_note, order_id))
            self.db.execute(
                """INSERT INTO positions (token_id, market_id, outcome, shares, cost, opened_ts, updated_ts)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(token_id) DO UPDATE SET shares=excluded.shares, cost=excluded.cost, updated_ts=excluded.updated_ts""",
                (token_id, market_id, outcome, round(have, 6), round(cost, 6), ts, ts))

    def settle(self, market_id: str, payout_yes: float, ts: float | None = None) -> float:
        """Pay out every position in a resolved market (YES shares pay payout_yes, NO shares 1 - payout_yes).
        Returns the cash credited."""
        ts = ts or time.time()
        total = 0.0
        with self.tx():
            for pos in self.q("SELECT * FROM positions WHERE market_id=? AND shares > 0.000001", (market_id,)):
                pay = float(payout_yes) if pos["outcome"] == "YES" else 1.0 - float(payout_yes)
                credit = float(pos["shares"]) * pay
                self.db.execute("INSERT INTO fills (ts, order_id, market_id, token_id, outcome, side, price, shares, fee) "
                                "VALUES (?,?,?,?,?,?,?,?,0)", (ts, None, market_id, pos["token_id"], pos["outcome"],
                                                               "SETTLE", pay, pos["shares"]))
                self._move_cash(credit, f"settle {pos['outcome']} {market_id} at {pay:g}", ts)
                self.db.execute("UPDATE positions SET shares=0, cost=0, updated_ts=? WHERE token_id=?", (ts, pos["token_id"]))
                total += credit
            self.db.execute("UPDATE markets SET closed=1, resolved_ts=COALESCE(resolved_ts, ?), payout_yes=? WHERE market_id=?",
                            (ts, float(payout_yes), market_id))
        return total

    # ---- exposure and equity ---------------------------------------------
    def exposure(self, market_id: str | None = None, event_id: str | None = None, category: str | None = None) -> dict:
        """Open cost in dollars: total, and for one market / event / category when given."""
        rows = self.q("""SELECT p.cost, p.market_id, m.event_id, m.category FROM positions p
                         LEFT JOIN markets m ON m.market_id = p.market_id WHERE p.shares > 0.000001""")
        out = {"total": 0.0, "market": 0.0, "event": 0.0, "category": 0.0}
        for r in rows:
            c = float(r["cost"])
            out["total"] += c
            if market_id is not None and r["market_id"] == market_id:
                out["market"] += c
            if event_id and r["event_id"] == event_id:
                out["event"] += c
            if category is not None and (r["category"] or "") == category:
                out["category"] += c
        return out

    def record_equity(self, marks: dict[str, tuple[float | None, float | None]], ts: float | None = None) -> dict:
        """marks: token_id -> (bid, mid). A position without a bid is valued at zero on the bid basis (what it
        would fetch right now) and at cost on the mid basis."""
        ts = ts or time.time()
        cash, bid_v, mid_v, n = self.cash(), 0.0, 0.0, 0
        for pos in self.positions():
            bid, mid = marks.get(pos["token_id"], (None, None))
            sh = float(pos["shares"])
            bid_v += sh * bid if bid else 0.0
            mid_v += sh * mid if mid else float(pos["cost"])
            n += 1
        row = {"ts": ts, "cash": cash, "positions_bid": bid_v, "positions_mid": mid_v, "equity": cash + bid_v, "n_positions": n}
        self.db.execute("INSERT OR REPLACE INTO equity (ts, cash, positions_bid, positions_mid, equity, n_positions) "
                        "VALUES (:ts, :cash, :positions_bid, :positions_mid, :equity, :n_positions)", row)
        self.db.commit()
        return row

    def last_equity(self, before: float | None = None):
        if before is None:
            return self.one("SELECT * FROM equity ORDER BY ts DESC LIMIT 1")
        return self.one("SELECT * FROM equity WHERE ts<=? ORDER BY ts DESC LIMIT 1", (before,))

    def high_water(self) -> float:
        r = self.one("SELECT MAX(equity) AS hw FROM equity")
        return float(r["hw"]) if r and r["hw"] is not None else 0.0

    def deposits(self) -> float:
        r = self.one("SELECT COALESCE(SUM(delta), 0) AS d FROM cash WHERE why LIKE 'deposit%'")
        return float(r["d"])

    # ---- runs --------------------------------------------------------------
    def start_run(self, run_id: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO runs (run_id, started, status) VALUES (?, ?, 'running')", (run_id, time.time()))
        self.db.commit()

    def finish_run(self, run_id: str, status: str, summary: dict | None = None) -> None:
        self.db.execute("UPDATE runs SET finished=?, status=?, summary=? WHERE run_id=?",
                        (time.time(), status, json.dumps(summary or {}), run_id))
        self.db.commit()

    def count_orders_since(self, since_ts: float, side: str = "BUY") -> tuple[int, float]:
        r = self.one("SELECT COUNT(*) AS n, COALESCE(SUM(usd), 0) AS usd FROM orders "
                     "WHERE ts>=? AND side=? AND status IN ('filled', 'partial', 'submitted')", (since_ts, side))
        return int(r["n"]), float(r["usd"])
