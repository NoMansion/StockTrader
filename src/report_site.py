"""The detailed daily report as one self-contained HTML page (published to GitHub Pages by
scripts/discord_report.py). The page is PUBLIC, so it shows percentages and weights only: no dollar amounts,
no share counts, no account details. Light and dark themes follow the viewer's system setting.

Sections: returns by period, account vs SPY since the start (hover for values), where the money is (stocks / IEF /
GLD / cash and stocks by sector), today's trades and the orders queued for the next open, every holding (sortable),
a day-by-day log, dividends, and a short description of the model.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import date

from src.discord_report import DUST_WEIGHT, SLEEVE


def _d(x: date) -> str:
    return x.strftime("%b %d, %Y").replace(" 0", " ")


def page_data(ctx: dict) -> dict:
    """Everything the page shows, as plain JSON (percent/weight only)."""
    eq = ctx["equity"]
    sectors = ctx.get("sectors") or {}
    curve = ctx.get("curve") or []
    base = curve[0][1] if curve else 1.0
    spy = dict(ctx.get("spy") or [])
    spy0 = next((spy[d] for d, _ in curve if d in spy), None)
    chart = [{"d": d.isoformat(), "acct": v / base - 1, "spy": (spy[d] / spy0 - 1) if (spy0 and d in spy) else None}
             for d, v in curve]

    pos = ctx["positions"]
    hold = sorted(pos, key=lambda p: -p["value"])          # every position, the tiny leftovers included
    dust = [p for p in pos if p["value"] / eq < DUST_WEIGHT]
    sector_of = lambda s: "Bonds (IEF)" if s in ("IEF", "TLT", "SHY") else "Gold (GLD)" if s == "GLD" else sectors.get(s, "Other")
    split = {"Stocks": sum(p["value"] for p in pos if p["symbol"] not in SLEEVE) / eq,
             "IEF": sum(p["value"] for p in pos if p["symbol"] == "IEF") / eq,
             "GLD": sum(p["value"] for p in pos if p["symbol"] == "GLD") / eq,
             "Cash": max(ctx["cash"], 0.0) / eq}
    by_sector = defaultdict(float)
    for p in pos:
        if p["symbol"] not in SLEEVE:
            by_sector[sector_of(p["symbol"])] += p["value"] / eq
    tr = ctx["trades"]
    trades = {k: [{"s": s, "w": v / eq} for s, v in tr[k]] for k in ("new", "added", "trimmed", "exited")}
    q = ctx.get("queued")
    queued = None if q is None else {"buys": q["buys"], "sells": q["sells"], "buy_w": q["buy_v"] / eq,
                                     "sell_w": q["sell_v"] / eq, "new": q["new_names"], "exit": q["exit_names"]}
    divs = [{"s": d["symbol"], "ex": d["ex_date"].isoformat(), "w": d["amount"] / eq} for d in ctx.get("div_items") or []]
    return {
        "date": ctx["today"].isoformat(), "date_long": ctx["today"].strftime("%A, %B %d, %Y").replace(" 0", " "),
        "paper": ctx["paper"], "updated": ctx.get("updated", ""),
        "returns": [{"label": r["label"], "pct": r["pct"], "since": _d(r["since"]) if r["since"] else None}
                    for r in ctx["returns"]],
        "chart": chart, "split": split, "sectors": sorted(by_sector.items(), key=lambda x: -x[1]),
        "holdings": [{"s": p["symbol"], "sector": sector_of(p["symbol"]), "w": p["value"] / eq, "day": p["day_pct"],
                      "total": p["total_pct"]} for p in hold],
        "dust": {"n": len(dust), "w": sum(p["value"] for p in dust) / eq},
        "trades": trades, "queued": queued, "history": ctx.get("history") or [],
        "div_mode": ctx["div_mode"], "div_total_w": ctx["div_total"] / eq, "divs": divs,
    }


CSS = """
:root{color-scheme:light;--bg:#f7f7f5;--surface:#fcfcfb;--line:#e4e3de;--ink:#0b0b0b;--ink2:#52514e;--muted:#7a796f;
--acct:#2a78d6;--spy:#eb6834;--pos:#2a78d6;--neg:#d03b3b;--stock:#6250d6;--ief:#1baf7a;--gld:#eda100;--cash:#a3a29a}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])){color-scheme:dark;--bg:#121211;--surface:#1a1a19;
--line:#383835;--ink:#f0efec;--ink2:#c3c2b7;--muted:#8a897f;--acct:#3987e5;--spy:#d95926;--pos:#3987e5;--neg:#e66767;
--stock:#9085e9;--ief:#199e70;--gld:#c98500;--cash:#6b6a64}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0}h2{font-size:17px;margin:0 0 12px}
.sub{color:var(--ink2);margin:2px 0 20px}.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px;margin:0 0 16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.tile{border:1px solid var(--line);border-radius:10px;padding:10px 12px}.tile .k{color:var(--ink2);font-size:13px}
.tile .v{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}.tile .n{color:var(--muted);font-size:12px}
.mark{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:baseline}
.legend{display:flex;gap:18px;color:var(--ink2);font-size:13px;margin:0 0 6px;flex-wrap:wrap}
#chart{position:relative}#chart svg{display:block;width:100%;height:auto}
.tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:8px 10px;
font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.18);display:none;white-space:nowrap;font-variant-numeric:tabular-nums}
.split{display:flex;gap:2px;height:30px;border-radius:6px;overflow:hidden;margin:4px 0 8px}.split div{min-width:2px}
.keys{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--ink2);font-size:14px}
.row{display:grid;grid-template-columns:minmax(105px,170px) 1fr 52px;gap:10px;align-items:center;font-size:14px;margin:5px 0}
.row .bar{height:12px;border-radius:0 4px 4px 0;background:var(--stock)}.row .num{text-align:right;font-variant-numeric:tabular-nums}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}
.list h3{font-size:14px;margin:0 0 6px;color:var(--ink2);font-weight:600}.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{border:1px solid var(--line);border-radius:6px;padding:2px 7px;font-size:13px;font-variant-numeric:tabular-nums}
.chip small{color:var(--muted)}table{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}
th{color:var(--ink2);font-weight:600;text-align:right;padding:6px 8px;border-bottom:1px solid var(--line);cursor:pointer;user-select:none;white-space:nowrap}
th:first-child,td:first-child,th.l,td.l{text-align:left}td{padding:6px 8px;text-align:right;border-bottom:1px solid var(--line)}
tr.sleeve td:first-child{font-weight:650}.scroll{overflow-x:auto}.note{color:var(--muted);font-size:13px;margin:8px 0 0}
.mini{display:inline-block;height:8px;border-radius:2px;vertical-align:middle;margin-left:6px}
p.about{color:var(--ink2);margin:0 0 8px}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const pct = (x, s=true) => x == null ? '—' : (s && x >= 0 ? '+' : '') + (x*100).toFixed(2) + '%';
const w1 = x => (x > 0 && x < 0.0005) ? '<0.1%' : (x*100).toFixed(1) + '%';
const wt = x => (x*100).toFixed(4).replace(/(\.\d*?[1-9])0+$/, '$1').replace(/\.0+$/, '.0') + '%';   // table: up to 4 decimals
const ax1 = v => (Math.abs(v) < 1e-9 ? '' : v > 0 ? '+' : '') + (v*100).toFixed(1) + '%';
const bp = x => '+' + (x*100).toFixed(3) + '%';
const el = (t, a={}, ...k) => { const e = document.createElement(t); for (const [n,v] of Object.entries(a)) n==='style'?e.style.cssText=v:e.setAttribute(n,v); k.flat().forEach(c => e.append(c)); return e; };

// returns tiles
const tiles = document.getElementById('tiles');
D.returns.forEach(r => tiles.append(el('div',{class:'tile'}, el('div',{class:'k'},r.label), el('div',{class:'v'},pct(r.pct)),
  el('div',{class:'n'}, r.since ? 'since ' + r.since : ' '))));

// account vs SPY chart (hover: crosshair + values)
(function(){
  const pts = D.chart; if (pts.length < 2) { document.getElementById('chart').textContent = 'Not enough history yet.'; return; }
  const box0 = document.getElementById('chart'), W = Math.max(300, Math.min(900, box0.clientWidth || 900)),
        H = W < 600 ? 230 : 300, L = 52, R = 12, T = 12, B = 30;
  const ys = pts.flatMap(p => [p.acct, p.spy]).filter(v => v != null);
  let lo = Math.min(0, ...ys), hi = Math.max(0, ...ys); const pad = (hi - lo) * 0.08 || 0.01; lo -= pad; hi += pad;
  const x = i => L + (W - L - R) * i / (pts.length - 1), y = v => T + (H - T - B) * (hi - v) / (hi - lo);
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const add = (t, a) => { const e = document.createElementNS(ns, t); for (const k in a) e.setAttribute(k, a[k]); svg.append(e); return e; };
  const step = niceStep((hi - lo) / 5);
  for (let v = Math.ceil(lo/step)*step; v <= hi; v += step) {
    add('line', {x1:L, x2:W-R, y1:y(v), y2:y(v), stroke: Math.abs(v)<1e-9 ? 'var(--muted)' : 'var(--line)', 'stroke-width':1});
    add('text', {x:L-8, y:y(v)+4, 'text-anchor':'end', 'font-size':12, fill:'var(--muted)'}).textContent = ax1(v);
  }
  const nl = Math.min(W < 600 ? 4 : 6, pts.length);
  for (let j = 0; j < nl; j++) { const i = Math.round(j * (pts.length-1) / Math.max(nl-1,1));
    add('text', {x:x(i), y:H-8, 'text-anchor': j===0?'start':j===nl-1?'end':'middle', 'font-size':12, fill:'var(--muted)'}).textContent =
      new Date(pts[i].d + 'T12:00').toLocaleDateString('en-US', {month:'short', day:'numeric'}); }
  const line = (k, c) => { const d = pts.map((p,i) => p[k]==null?null:[x(i),y(p[k])]).filter(Boolean);
    if (d.length > 1) add('path', {d:'M'+d.map(q=>q.join(',')).join('L'), fill:'none', stroke:c, 'stroke-width':2, 'stroke-linejoin':'round'}); };
  line('spy', 'var(--spy)'); line('acct', 'var(--acct)');
  const cross = add('line', {y1:T, y2:H-B, stroke:'var(--muted)', 'stroke-width':1, visibility:'hidden'});
  const dA = add('circle', {r:5, fill:'var(--acct)', stroke:'var(--surface)', 'stroke-width':2, visibility:'hidden'});
  const dS = add('circle', {r:5, fill:'var(--spy)', stroke:'var(--surface)', 'stroke-width':2, visibility:'hidden'});
  const box = document.getElementById('chart'); box.append(svg); const tip = el('div', {class:'tip'}); box.append(tip);
  const hit = add('rect', {x:L, y:T, width:W-L-R, height:H-T-B, fill:'transparent'});
  hit.addEventListener('pointermove', ev => {
    const r = svg.getBoundingClientRect(), sx = (ev.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(pts.length-1, Math.round((sx - L) / (W-L-R) * (pts.length-1)))), p = pts[i];
    [cross, dA, dS].forEach(e => e.setAttribute('visibility','visible'));
    cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i));
    dA.setAttribute('cx', x(i)); dA.setAttribute('cy', y(p.acct));
    if (p.spy != null) { dS.setAttribute('cx', x(i)); dS.setAttribute('cy', y(p.spy)); } else dS.setAttribute('visibility','hidden');
    tip.innerHTML = `<b>${new Date(p.d+'T12:00').toLocaleDateString('en-US',{weekday:'short',month:'short',day:'numeric'})}</b><br>` +
      `<span class="mark" style="background:var(--acct)"></span>Account ${pct(p.acct)}<br>` +
      `<span class="mark" style="background:var(--spy)"></span>SPY ${pct(p.spy)}`;
    tip.style.display = 'block'; const px = x(i) * r.width / W;
    tip.style.left = Math.min(px + 12, r.width - tip.offsetWidth - 4) + 'px'; tip.style.top = '8px';
  });
  hit.addEventListener('pointerleave', () => { [cross, dA, dS].forEach(e => e.setAttribute('visibility','hidden')); tip.style.display='none'; });
  function niceStep(r){ const m = Math.pow(10, Math.floor(Math.log10(r))); for (const k of [1,2,2.5,5,10]) if (k*m >= r) return k*m; return 10*m; }
})();

// where the money is
(function(){
  const c = {Stocks:'var(--stock)', IEF:'var(--ief)', GLD:'var(--gld)', Cash:'var(--cash)'};
  const bar = document.getElementById('split'), keys = document.getElementById('splitkeys');
  Object.entries(D.split).forEach(([k,v]) => { if (v <= 0) return; bar.append(el('div',{style:`flex:${v};background:${c[k]}`, title:`${k} ${w1(v)}`}));
    keys.append(el('span',{}, el('span',{class:'mark',style:`background:${c[k]}`}), `${k} ${w1(v)}`)); });
  const sec = document.getElementById('sectors'), mx = Math.max(...D.sectors.map(s => s[1]), 1e-9);
  D.sectors.forEach(([n,v]) => sec.append(el('div',{class:'row'}, el('span',{},n), el('div',{class:'bar',style:`width:${v/mx*100}%`}), el('span',{class:'num'},w1(v)))));
})();

// trades
(function(){
  const box = document.getElementById('trades'), names = {new:'New buys', added:'Added to', trimmed:'Trimmed', exited:'Sold out'};
  let any = false;
  for (const k of ['new','added','trimmed','exited']) { const t = D.trades[k]; if (!t.length) continue; any = true;
    box.append(el('div',{class:'list'}, el('h3',{}, `${names[k]} (${t.length})`),
      el('div',{class:'chips'}, t.map(x => el('span',{class:'chip'}, x.s + ' ', el('small',{}, w1(x.w))))))); }
  if (!any) box.append(el('p',{class:'note'},'No trades today.'));
  const q = D.queued, qb = document.getElementById('queued');
  if (!q) qb.textContent = 'Orders for the next open are listed after the evening run.';
  else if (q.buys + q.sells === 0) qb.textContent = 'No orders queued for the next open.';
  else qb.textContent = `Queued for the next open: ${q.buys} buys (${w1(q.buy_w)} of the account), ${q.sells} sells (${w1(q.sell_w)})` +
    (q.new.length ? `. New: ${q.new.join(', ')}` : '') + (q.exit.length ? `. Selling out: ${q.exit.join(', ')}` : '') + '.';
})();

// holdings (click a header to sort)
(function(){
  const rows = D.holdings.slice(), tb = document.querySelector('#hold tbody'), mx = Math.max(...rows.map(r => Math.abs(r.total)), 0.01);
  const draw = () => { tb.innerHTML = ''; rows.forEach(r => tb.append(el('tr',{class: ['IEF','GLD','TLT','SHY'].includes(r.s) ? 'sleeve' : ''},
    el('td',{},r.s), el('td',{class:'l'},r.sector), el('td',{},wt(r.w)), el('td',{},pct(r.day)),
    el('td',{}, pct(r.total), el('span',{class:'mini',style:`width:${Math.max(2,Math.abs(r.total)/mx*40)}px;background:${r.total>=0?'var(--pos)':'var(--neg)'}`}))))); };
  let key = 'w', dir = -1;
  document.querySelectorAll('#hold th').forEach(th => th.addEventListener('click', () => { const k = th.dataset.k;
    dir = (k === key) ? -dir : (k === 's' || k === 'sector' ? 1 : -1); key = k;
    rows.sort((a,b) => (a[k] > b[k] ? 1 : a[k] < b[k] ? -1 : 0) * dir); draw(); }));
  draw();
  if (D.dust.n) document.getElementById('dust').textContent = `${D.dust.n} of these positions are under 0.1% of the account (${w1(D.dust.w)} in total): leftover fractional shares from sells.`;
})();

// day-by-day log (newest first)
(function(){
  const tb = document.querySelector('#log tbody');
  D.history.slice().reverse().forEach(h => tb.append(el('tr',{}, el('td',{}, new Date(h.d+'T12:00').toLocaleDateString('en-US',{weekday:'short',month:'short',day:'numeric'})),
    el('td',{},pct(h.day)), el('td',{},pct(h.spy)), el('td',{},pct(h.cum)), el('td',{},String(h.buys)), el('td',{},String(h.sells)))));
})();

// dividends
(function(){
  const box = document.getElementById('divs');
  const head = D.div_mode === 'estimated'
    ? `Estimated dividends add ${pct(D.div_total_w)} to the returns above. The paper account is not paid dividends, so each one is estimated from the shares held the night before its ex-date.`
    : `Dividends received add ${pct(D.div_total_w)} (already in the account value).`;
  box.append(el('p',{class:'note',style:'margin-top:0'}, head));
  if (D.divs.length) box.append(el('div',{class:'chips'}, D.divs.slice().reverse().map(d => el('span',{class:'chip'}, d.s + ' ',
    el('small',{}, new Date(d.ex+'T12:00').toLocaleDateString('en-US',{month:'short',day:'numeric'}) + ' · ' + bp(d.w))))));
})();
"""


def build_html(ctx: dict) -> str:
    data = page_data(ctx)
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    acct = "Paper account" if ctx["paper"] else "Live account"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>StockTrader daily report</title><style>{CSS}</style></head>
<body><main>
<h1>StockTrader daily report</h1>
<p class="sub">{html.escape(data['date_long'])} · {acct} · updated {html.escape(data['updated'])} · percentages only, no dollar amounts</p>

<section class="card"><h2>Returns</h2><div class="tiles" id="tiles"></div>
<p class="note">Change in account value{', including estimated dividends' if ctx['div_mode'] == 'estimated' else ''}. "Since" means the account is younger than that period.</p></section>

<section class="card"><h2>Account vs the S&amp;P 500 since the start</h2>
<div class="legend"><span><span class="mark" style="background:var(--acct)"></span>Account</span>
<span><span class="mark" style="background:var(--spy)"></span>SPY (S&amp;P 500 ETF, dividends reinvested)</span></div>
<div id="chart"></div></section>

<section class="card"><h2>Where the money is</h2><div class="split" id="split"></div><div class="keys" id="splitkeys"></div>
<h2 style="margin-top:20px">Stocks by sector <span class="note">(% of the whole account)</span></h2><div id="sectors"></div></section>

<section class="card"><h2>Today's trades</h2><p class="note" style="margin:-6px 0 12px">Filled at today's open; size as % of the account.</p>
<div class="cols" id="trades"></div><p class="note" id="queued"></p></section>

<section class="card"><h2>Holdings ({len(data['holdings'])})</h2><div class="scroll"><table id="hold"><thead><tr>
<th data-k="s">Symbol</th><th data-k="sector" class="l">Sector</th><th data-k="w">Weight</th><th data-k="day">Today</th><th data-k="total">Since bought</th>
</tr></thead><tbody></tbody></table></div><p class="note" id="dust"></p><p class="note">Click a column header to sort.</p></section>

<section class="card"><h2>Day by day</h2><div class="scroll"><table id="log"><thead><tr>
<th>Date</th><th>Account</th><th>SPY</th><th>Since start</th><th>Names bought</th><th>Names sold</th>
</tr></thead><tbody></tbody></table></div></section>

<section class="card"><h2>Dividends</h2><div id="divs"></div></section>

<section class="card"><h2>How the model works</h2>
<p class="about">Each evening it takes the US stocks ranked 151st to 3,000th by dollar trading volume, scores them on a mix of earnings surprise, free-cash-flow yield and six quality/value measures, skips financially weak companies (Altman Z below 1.81), buys a new name only within 42 trading days of its last earnings filing, and holds the top 45: at most 11 from one sector, sized by the square root of company size.</p>
<p class="about">How much goes into stocks is set by market conditions: a 15% volatility target (10-day), halved when the market's 12-month return is negative, halved when more NYSE stocks hit new lows than new highs over 5 days, halved when the NYSE advance/decline line is below its 100-day average, and halved when the equity put/call ratio is in the lowest 5% of its past year (complacency). The rest goes into IEF (7-10 year Treasuries) and GLD (gold).</p>
<p class="note">Orders are placed after the close and fill at the next day's open. This is a research project, not investment advice.</p></section>
</main>
<script type="application/json" id="data">{blob}</script>
<script>{JS}</script>
</body></html>"""
