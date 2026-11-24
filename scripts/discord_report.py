"""Daily report: a short Discord post (one embed + a dashboard image) linking to a detailed page on GitHub Pages.

    python scripts/discord_report.py              # publish the page, then post to DISCORD_REPORT_CHANNEL_ID
    python scripts/discord_report.py --dry-run    # print the embed, save dashboard.png + report.html to data/, post nothing
    python scripts/discord_report.py --no-site    # post without publishing the page
    python scripts/discord_report.py --wait       # first wait (up to 40 min) for a running daily job to finish

Runs once and exits: no bot process stays running. It only reads from Alpaca (account, positions, fills, open
orders, dividend calendar, SPY closes) and never submits or cancels an order. A few dozen small web requests, no
market-data files, well under 300 MB of memory. The report covers the latest session whose close has passed.

The page (src/report_site.py) is PUBLIC (gh-pages branch of the repo, one fresh commit each day, no history), so it
holds percentages and weights only, never dollar amounts. The Discord post has dollars; the channel is private.

Settings (.env, never committed): DISCORD_REPORT_CHANNEL_ID, REPORT_SITE_URL; DISCORD_TOKEN, or else the bot's own
.env at DISCORD_BOT_ENV (default: DiscordBot/.env next to this project's folder). Fill history is cached in data/discord_fills_cache.json.
"""
import _bootstrap  # noqa: F401

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from src import discord_report as rep

ET = ZoneInfo("America/New_York")
CACHE = Path("data/discord_fills_cache.json")
UA = "DiscordBot (https://example.invalid, 1.0)"


class Alpaca:
    def __init__(self):
        self.paper = os.environ.get("ALPACA_PAPER", "true").lower() == "true"
        self.base = "https://paper-api.alpaca.markets" if self.paper else "https://api.alpaca.markets"
        self.data = "https://data.alpaca.markets"
        self.h = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}

    def get(self, path: str, base: str | None = None, **params):
        r = requests.get((base or self.base) + path, headers=self.h, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def activities(self, kind: str, after: str | None) -> list[dict]:
        out, token = [], None
        while True:
            p = {"activity_types": kind, "direction": "asc", "page_size": 100}
            if after:
                p["after"] = after
            if token:
                p["page_token"] = token
            batch = self.get("/v2/account/activities", **p)
            out += batch
            if len(batch) < 100:
                return out
            token = batch[-1]["id"]


def et_date(ts: str) -> date:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ET).date()


def cache_path(account_id: str) -> Path:
    return Path(f"data/discord_fills_{account_id}.json")


def read_cache(account_id: str, paper: bool) -> list[dict]:
    """This account's cached fills. Each account has its own file, tagged with its id, so paper fills never leak into
    the live report. The first cache (before 2026-11-18) was untagged and came from the paper account: a paper run
    adopts it, a live run ignores it."""
    p = cache_path(account_id)
    if p.exists():
        d = json.loads(p.read_text())
        return d["fills"] if d.get("account") == account_id else []
    if paper and CACHE.exists():
        legacy = json.loads(CACHE.read_text())
        if isinstance(legacy, list):
            return legacy
    return []


def load_fills(api: Alpaca, start: str, account_id: str) -> list[dict]:
    """All FILL activities since the account opened, cached locally (per account) and topped up each run."""
    cache = read_cache(account_id, api.paper)
    seen = {f["id"] for f in cache}
    after = (max(f["time"] for f in cache) if cache else start)
    # step back a minute: fills sharing the boundary timestamp are not skipped; `seen` drops the repeats
    after = (datetime.fromisoformat(after.replace("Z", "+00:00")) - timedelta(minutes=1)).isoformat()
    for a in api.activities("FILL", after):
        if a["id"] in seen:
            continue
        seen.add(a["id"])
        cache.append({"id": a["id"], "symbol": a["symbol"], "side": "buy" if a["side"] == "buy" else "sell",
                      "qty": a["qty"], "price": a["price"], "time": a["transaction_time"]})
    cache.sort(key=lambda f: f["time"])
    p = cache_path(account_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"account": account_id, "fills": cache}))
    if api.paper and CACHE.exists():
        CACHE.unlink()           # the untagged legacy file now lives on as the paper account's tagged cache
    return [{**f, "date": et_date(f["time"])} for f in cache]


def report_day(api: Alpaca, now: datetime) -> tuple[date, bool]:
    """Latest session whose close has passed, and whether that session is today."""
    cal = api.get("/v2/calendar", start=(now.date() - timedelta(days=12)).isoformat(), end=now.date().isoformat())
    done = [date.fromisoformat(c["date"]) for c in cal
            if date.fromisoformat(c["date"]) < now.date()
            or (c["date"] == now.date().isoformat() and now.strftime("%H:%M") >= c["close"])]
    d = max(done)
    return d, d == now.date()


def dividends(api: Alpaca, symbols: list[str], start: date, end: date) -> list[dict]:
    out = []
    for i in range(0, len(symbols), 50):
        token = None
        while True:
            p = {"symbols": ",".join(symbols[i:i + 50]), "types": "cash_dividend", "start": start.isoformat(),
                 "end": end.isoformat(), "limit": 1000}
            if token:
                p["page_token"] = token
            j = api.get("/v1/corporate-actions", base=api.data, **p)
            for d in j.get("corporate_actions", {}).get("cash_dividends", []):
                out.append({"symbol": d["symbol"], "ex_date": date.fromisoformat(d["ex_date"]), "rate": float(d["rate"]),
                            "payable_date": date.fromisoformat(d["payable_date"]) if d.get("payable_date") else None})
            token = j.get("next_page_token")
            if not token:
                break
    return out


def daily_job_running() -> bool:
    cmd = ["powershell", "-NoProfile", "-Command",
           "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'run_daily(_retry)?\\.py' }).Count"]
    try:
        return int((subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout or "0").strip() or 0) > 0
    except (subprocess.SubprocessError, ValueError, OSError):
        return False


def build(api: Alpaca) -> dict:
    now = datetime.now(ET)
    acct = api.get("/v2/account")
    D, is_today = report_day(api, now)
    start = et_date(acct["created_at"])

    ph = api.get("/v2/account/portfolio/history", start=start.isoformat(), timeframe="1D", intraday_reporting="market_hours",
                 cashflow_types="ALL")
    ph_dates = [datetime.fromtimestamp(t, ET).date() for t in ph["timestamp"]]
    series = {d: float(e) for d, e in zip(ph_dates, ph["equity"]) if e}
    series = {d: v for d, v in series.items() if d <= D}
    if D not in series:          # the close of D is not in the history yet: use the live account value
        series[D] = float(acct["equity"])
    dates = sorted(series)

    fills = load_fills(api, acct["created_at"], acct["id"])
    # deposits / withdrawals after the first trade (the initial funding is the starting value): not gains
    flows = rep.external_flows(ph.get("cashflow") or {}, ph_dates, min((f["date"] for f in fills), default=None))
    flows = {d: x for d, x in flows.items() if d <= D}
    real_divs = api.activities("DIV", acct["created_at"])
    if real_divs:
        mode = "actual"
        items = [{"symbol": a.get("symbol", ""), "amount": float(a.get("net_amount", 0)),
                  "ex_date": date.fromisoformat(a["date"])} for a in real_divs]
        key = "ex_date"
        values = [series[d] for d in dates]
    elif api.paper:
        mode = "estimated"
        syms = sorted({f["symbol"] for f in fills})
        # the API's start/end filter on the pay/process date, not the ex-date: ask wide, estimated_dividends() keeps
        # the ex-dates that fall while a position was held, up to D
        divs = dividends(api, syms, start - timedelta(days=30), D + timedelta(days=90)) if syms else []
        items = rep.estimated_dividends(fills, divs, D)
        key = "ex_date"
        cum = rep.cumulative_by_date(items, key, dates)
        values = [series[d] + c for d, c in zip(dates, cum)]
    else:
        mode, items, key, values = "actual", [], "ex_date", [series[d] for d in dates]
    returns = rep.period_returns(list(zip(dates, values)), D, flows)
    curve = rep.growth_index(list(zip(dates, values)), flows)    # chart / page / day log: deposits taken out
    prev = dates[-2] if len(dates) > 1 else start
    div_windows = {"Today": rep.dividends_in_window(items, key, prev, D),
                   "Week": rep.dividends_in_window(items, key, D - timedelta(days=7), D),
                   "Month": rep.dividends_in_window(items, key, rep._months_back(D, 1), D),
                   "YTD": rep.dividends_in_window(items, key, date(D.year - 1, 12, 31), D)}

    pos_raw = api.get("/v2/positions")
    positions = [{"symbol": p["symbol"], "qty": float(p["qty"]), "value": float(p["market_value"]),
                  "day_pct": float(p.get("change_today") or 0), "total_pct": float(p.get("unrealized_plpc") or 0),
                  "day_pl": float(p.get("unrealized_intraday_pl") or 0)} for p in pos_raw]
    qty_now = {p["symbol"]: p["qty"] for p in positions}
    px = {p["symbol"]: (p["value"] / p["qty"] if p["qty"] else 0.0) for p in positions}
    trades = rep.trades_today([f for f in fills if f["date"] == D], qty_now, px)

    queued = None
    if is_today:
        orders = api.get("/v2/orders", status="open", limit=500)
        need = sorted({o["symbol"] for o in orders if o["symbol"] not in px})
        if need:
            lt = api.get("/v2/stocks/trades/latest", base=api.data, symbols=",".join(need), feed="iex").get("trades", {})
            px.update({s: float(t["p"]) for s, t in lt.items()})
        q = {"buys": 0, "sells": 0, "buy_v": 0.0, "sell_v": 0.0, "new_names": [], "exit_names": []}
        sell_q = {}
        for o in orders:
            v = float(o["notional"]) if o.get("notional") else float(o.get("qty") or 0) * px.get(o["symbol"], 0.0)
            side = "buy" if o["side"] == "buy" else "sell"
            q[side + "s"] += 1
            q[side + "_v"] += v
            if side == "sell":
                sell_q[o["symbol"]] = sell_q.get(o["symbol"], 0.0) + (float(o["qty"]) if o.get("qty") else v / max(px.get(o["symbol"], 1e-9), 1e-9))
        held_v = {p["symbol"]: p["value"] for p in positions}
        q["new_names"] = sorted({o["symbol"] for o in orders if o["side"] == "buy" and held_v.get(o["symbol"], 0.0) < 1.0})
        q["exit_names"] = sorted(s for s, sq in sell_q.items() if sq >= 0.999 * qty_now.get(s, 0.0) and held_v.get(s, 0) >= 1.0)
        queued = q

    ctx = {"today": D, "paper": api.paper, "equity": float(series[D]), "cash": float(acct["cash"]), "returns": returns,
           "div_mode": mode, "div_total": sum(i["amount"] for i in items), "div_windows": div_windows,
           "positions": positions, "trades": trades, "queued": queued, "curve": curve, "flows": flows,
           "div_items": items, "updated": now.astimezone(ZoneInfo("America/Chicago")).strftime("%b %d, %I:%M %p CT").replace(" 0", " ")}
    ctx["spy"] = spy_closes(api, dates[0], D)
    ctx["history"] = rep.daily_history(ctx["curve"], ctx["spy"], fills)
    sp = Path("data/sectors.json")
    ctx["sectors"] = json.loads(sp.read_text()) if sp.exists() else {}
    return ctx


def spy_closes(api: Alpaca, start: date, end: date) -> list[tuple[date, float]]:
    """SPY daily closes, adjusted for dividends (the benchmark line on the page)."""
    # no `end`: the free data plan refuses SIP requests that reach the last 15 minutes; filter to <= end here instead
    for feed in ("sip", "iex"):
        try:
            j = api.get("/v2/stocks/bars", base=api.data, symbols="SPY", timeframe="1Day", start=start.isoformat(),
                        adjustment="all", feed=feed, limit=10000)
        except requests.RequestException:
            continue
        rows = [(date.fromisoformat(b["t"][:10]), float(b["c"])) for b in j.get("bars", {}).get("SPY", [])]
        return [(d, c) for d, c in rows if d <= end]
    return []


def _git(*args, cwd: Path, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=180)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def publish_site(page: str, day: date) -> str | None:
    """Push the page to the repo's gh-pages branch as one fresh commit (no history kept) and wait up to 3 min for
    GitHub Pages to build it. Returns the commit sha, or None if it could not be published."""
    root = Path(__file__).resolve().parent.parent
    site = root / "data" / "site"
    site.mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(page, encoding="utf-8")
    (site / ".nojekyll").write_text("")
    try:
        remote = _git("remote", "get-url", "origin", cwd=root)
        who = ["-c", f"user.name={_git('config', 'user.name', cwd=root)}", "-c", f"user.email={_git('config', 'user.email', cwd=root)}"]
        if not (site / ".git").exists():
            _git("init", "-q", cwd=site)
        _git("checkout", "-q", "--orphan", "publish", cwd=site, check=False)
        _git("add", "-A", cwd=site)
        _git(*who, "commit", "-q", "-m", f"Daily report {day.isoformat()}", cwd=site)
        _git("branch", "-D", "gh-pages", cwd=site, check=False)
        _git("branch", "-m", "gh-pages", cwd=site)
        sha = _git("rev-parse", "HEAD", cwd=site)
        _git("push", "-q", "-f", remote, "gh-pages", cwd=site)
        _git("gc", "-q", "--prune=now", cwd=site, check=False)
    except (RuntimeError, subprocess.SubprocessError, OSError) as e:
        print(f"site not published: {e}", flush=True)
        return None
    slug = remote.rstrip("/").removesuffix(".git").split("github.com")[-1].lstrip(":/")
    for _ in range(18):
        time.sleep(10)
        try:
            r = subprocess.run(["gh", "api", f"repos/{slug}/pages/builds/latest", "--jq", '.status + " " + .commit'],
                               capture_output=True, text=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            break
        status, _, commit = r.stdout.strip().partition(" ")
        if commit == sha and status == "built":
            print("site published and built", flush=True)
            return sha
        if commit == sha and status == "errored":
            print("GitHub Pages build failed", flush=True)
            return sha
    print("site pushed; GitHub Pages build not confirmed yet", flush=True)
    return sha


def post(emb: dict, image: tuple[str, bytes] | None, site_url: str | None, channel: str, token: str) -> None:
    """One message: the embed (with the dashboard image inside it) and a "Full report" link button."""
    h = {"Authorization": f"Bot {token}", "User-Agent": UA}
    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    payload = {"embeds": [emb], "allowed_mentions": {"parse": []}}
    if site_url:
        payload["components"] = [{"type": 1, "components": [{"type": 2, "style": 5, "label": "Full report", "url": site_url}]}]
    if image:
        payload["attachments"] = [{"id": 0, "filename": image[0]}]
    for _ in range(3):
        files = {"files[0]": (image[0], image[1], "image/png")} if image else None
        r = requests.post(url, headers=h, data={"payload_json": json.dumps(payload)}, files=files, timeout=60)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Discord rejected the report: {r.status_code} {r.text[:300]}")
        return
    raise RuntimeError("Discord kept rate-limiting the report")


def discord_token() -> str | None:
    if os.environ.get("DISCORD_TOKEN"):
        return os.environ["DISCORD_TOKEN"]
    p = Path(os.environ.get("DISCORD_BOT_ENV", Path(__file__).resolve().parents[2] / "DiscordBot" / ".env"))
    if p.exists():
        from dotenv import dotenv_values
        return dotenv_values(p).get("DISCORD_TOKEN")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wait", action="store_true", help="wait up to 40 min for a running daily job to finish first")
    ap.add_argument("--channel", default=os.environ.get("DISCORD_REPORT_CHANNEL_ID"))
    ap.add_argument("--save-images", default="data", help="with --dry-run: folder for the PNG and the HTML page")
    ap.add_argument("--no-site", action="store_true", help="post to Discord without publishing the page")
    ap.add_argument("--site-only", action="store_true", help="publish the page without posting to Discord")
    args = ap.parse_args()
    print(f"===== discord report {datetime.now(ET):%Y-%m-%d %I:%M %p} ET =====", flush=True)
    if args.wait:
        for _ in range(40):
            if not daily_job_running():
                break
            print("daily job still running: waiting 1 min", flush=True)
            time.sleep(60)
    ctx = build(Alpaca())
    from src import report_images, report_site   # matplotlib is imported only now, after the data is in
    page = report_site.build_html(ctx)
    png = report_images.dashboard(ctx)
    site_url = os.environ.get("REPORT_SITE_URL") or None
    if args.dry_run:
        out = Path(args.save_images)
        (out / "dashboard.png").write_bytes(png)
        (out / "report.html").write_text(page, encoding="utf-8")
        print(json.dumps(rep.embed(ctx, site_url, "dashboard.png"), indent=1, ensure_ascii=False))
        print("wrote", out / "dashboard.png", f"{len(png) / 1024:.0f} KB and", out / "report.html", f"{len(page) / 1024:.0f} KB")
        return
    if args.site_only:
        ok = site_url and publish_site(page, ctx["today"]) is not None
        print("published the page" if ok else "the page was NOT published (REPORT_SITE_URL unset or the push failed)", flush=True)
        return
    if site_url and not args.no_site:
        if publish_site(page, ctx["today"]) is None:
            site_url = None        # do not link a page that did not update
        else:
            site_url += f"?d={ctx['today'].isoformat()}"     # a new link each day, so no stale cached copy
    token = discord_token()
    if not (token and args.channel):
        sys.exit("Set DISCORD_REPORT_CHANNEL_ID and DISCORD_TOKEN (or DISCORD_BOT_ENV) in .env")
    post(rep.embed(ctx, site_url, "dashboard.png"), ("dashboard.png", png), site_url, args.channel, token)
    print(f"posted the report{' with the page link' if site_url else ''}", flush=True)


if __name__ == "__main__":
    main()
