// Kil Capital Terminal: static dashboard. Reads data/state.json (rebuilt by GitHub Actions every few minutes)
// and, where the browser is allowed to, refreshes prices straight from Kalshi's public market data so
// edges and stakes stay live between rebuilds. Recommend-only: nothing here can place an order.
"use strict";

const KALSHI = "https://api.elections.kalshi.com/trade-api/v2";
const STATE_EVERY = 60e3, LIVE_EVERY = 15e3, LIVE_RETRY = 300e3, STALE_MIN = 30;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const usd = (v, d = 0) => v == null ? "–" : (v < 0 ? "−$" : "$") + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const cents = (p) => p == null ? "–" : Math.round(p * 100) + "¢";
const pct = (v, d = 1, sign = false) => v == null ? "–" : (sign && v > 0 ? "+" : "") + (v * 100).toFixed(d) + "%";
const fee = (p) => 0.07 * p * (1 - p);

let S = null, liveOk = null, liveTimer = null;
const TZ = "America/Chicago", WIN_MIN = 0.55;
const F = { w: "today", q: "", league: "", conf: "", kind: "", grade: "", top25: false, rvr: false, win: true, sort: "profit" };
const legs = new Set();     // tickers ticked for the parlay
const quotes = new Map();   // ticker -> {yes, no} live asks

// ---------- live pricing (mirrors sports/segments.size) ----------
function reprice(p) {
  const q = quotes.get(p.ticker);
  const price = q ? q[p.side] : null;
  if (price == null || !(price > 0 && price < 1)) return { ...p, live: false };
  const c = price + fee(price);
  const f = c < 1 ? Math.max(0, (p.fair - c) / (1 - c)) : 0;
  const stake = Math.min(S.max_trade, (S.kelly_fraction ?? 0.25) * f * (p.segment_mult ?? 1) * S.bankroll);
  const count = Math.floor(stake / c);
  return { ...p, live: true, prev: p.price, price, edge: p.fair - price - fee(price),
    count, stake: +(count * c).toFixed(2), roi: (p.fair - c) / c, exp_profit: +(count * (p.fair - c)).toFixed(2) };
}

const ymd = (t) => new Date(t).toLocaleDateString("en-CA", { timeZone: TZ });
const teamsOf = (p) => p.teams || [];
const ranked = (p) => teamsOf(p).filter((t) => t.rank).length;

function inWindow(p) {
  if (!p.start) return true;                                   // crypto: always open
  const t = Date.parse(p.start), now = Date.now();
  if (F.w === "today") return t < now || ymd(t) === ymd(now);  // started counts as today
  return t < now + 7 * 864e5;
}

function matches(p) {
  if (!inWindow(p)) return false;
  if (F.league && (p.desk === "crypto" ? "Crypto" : p.league) !== F.league) return false;
  if (F.kind && p.kind !== F.kind) return false;
  if (F.grade && !F.grade.includes(p.confidence)) return false;
  if (F.conf && !teamsOf(p).some((t) => t.conf === F.conf)) return false;
  if (F.top25 && !ranked(p)) return false;
  if (F.rvr && ranked(p) < 2) return false;
  if (F.win && !(p.fair >= WIN_MIN && p.edge > 0)) return false;
  if (F.q) {
    const hay = [p.title, ...teamsOf(p).flatMap((t) => [t.name, t.abbr, t.nick])].join(" ").toLowerCase();
    if (!F.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
  }
  return true;
}

const SORTS = { profit: (a, b) => b.exp_profit - a.exp_profit, win: (a, b) => b.fair - a.fair,
  edge: (a, b) => b.edge - a.edge, start: (a, b) => (a.start || "9") < (b.start || "9") ? -1 : 1 };
function picks() { return (S?.picks || []).map(reprice).filter(matches).sort(SORTS[F.sort] || SORTS.profit); }

async function pullLive() {
  const tickers = [...new Set((S?.picks || []).map((p) => p.ticker))];
  if (!tickers.length) return;
  try {
    for (let i = 0; i < tickers.length; i += 50) {
      const r = await fetch(`${KALSHI}/markets?tickers=${encodeURIComponent(tickers.slice(i, i + 50).join(","))}&limit=100`,
        { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      for (const m of (await r.json()).markets || []) {
        const px = (k) => m[`${k}_dollars`] != null ? +m[`${k}_dollars`] : m[k] != null ? m[k] / 100 : null;
        quotes.set(m.ticker, { yes: px("yes_ask"), no: px("no_ask") });
      }
    }
    liveOk = true;
  } catch {
    liveOk = false;                       // blocked (CORS) or offline: fall back to the 15-minute snapshot
  }
  setFeed();
  renderPicks(true);
  renderKpis();
  clearTimeout(liveTimer);
  liveTimer = setTimeout(pullLive, liveOk ? LIVE_EVERY : LIVE_RETRY);
}

// ---------- state ----------
async function pullState() {
  try {
    const r = await fetch(`data/state.json?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    S = await r.json();
    render();
    if (liveOk === null) pullLive();
  } catch (e) {
    if (!S) $("#noPicks").hidden = false, $("#noPicks").textContent = "Waiting for the first refresh from GitHub Actions.";
  }
  setFeed();
}

function ageMin() { return S ? (Date.now() - Date.parse(S.generated)) / 60e3 : Infinity; }

function setFeed() {
  const el = $("#feed"), lab = $("#feedLabel"), a = ageMin();
  el.className = "feed " + (a > STALE_MIN ? "stale" : liveOk ? "live" : "snap");
  lab.textContent = a > STALE_MIN ? "Stale" : liveOk ? "Live prices" : "Auto-refreshing";
  $("#updated").textContent = S ? `Models ${a < 1 ? "just now" : Math.round(a) + " min ago"}` : "–";
}

// ---------- render ----------
function render() {
  $("#bankroll").textContent = usd(S.bankroll);
  renderFilters(); renderKpis(); renderPicks(); renderExposure(); renderParlay(); renderCrypto(); renderHealth(); renderSlate(); renderTrack();
  const errs = S.errors || [];
  $("#errors").hidden = !errs.length;
  $("#errors").textContent = errs.length ? "Data notes: " + errs.join(" · ") : "";
}

const ctl = { q: "#q", league: "#fLeague", conf: "#fConf", kind: "#fKind", grade: "#fGrade", top25: "#fTop25", rvr: "#fRvR", win: "#fWin", sort: "#fSort" };
const DEF = { ...F };

function loadUrl() {
  const u = new URLSearchParams(location.search);
  for (const k of Object.keys(F)) if (u.has(k)) F[k] = typeof DEF[k] === "boolean" ? u.get(k) === "1" : u.get(k);
}
function saveUrl() {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(F)) if (v !== DEF[k]) u.set(k, typeof v === "boolean" ? (v ? "1" : "0") : v);
  history.replaceState(null, "", u.toString() ? "?" + u : location.pathname);
}

function options(sel, vals, all) {
  const cur = F[Object.keys(ctl).find((k) => ctl[k] === sel)];
  $(sel).innerHTML = `<option value="">${all}</option>` + vals.map((v) => `<option${v === cur ? " selected" : ""}>${esc(v)}</option>`).join("");
}

function renderFilters() {
  const ps = S.picks || [];
  options("#fLeague", [...new Set(ps.map((p) => p.desk === "crypto" ? "Crypto" : p.league))].sort(), "All leagues");
  options("#fConf", [...new Set(ps.flatMap((p) => teamsOf(p).map((t) => t.conf)).filter(Boolean))].sort(), "All conferences");
  for (const [k, sel] of Object.entries(ctl)) { const el = $(sel); if (el.type === "checkbox") el.checked = F[k]; else el.value = F[k]; }
  for (const b of document.querySelectorAll("#when button")) b.setAttribute("aria-selected", b.dataset.w === F.w);
  const n = Object.keys(F).filter((k) => k !== "w" && k !== "sort" && F[k] !== DEF[k]).length;
  $("#fCount").textContent = n ? `(${n})` : "";
}

function onFilter() {
  for (const [k, sel] of Object.entries(ctl)) { const el = $(sel); F[k] = el.type === "checkbox" ? el.checked : el.value; }
  update();
}
function update() { saveUrl(); renderFilters(); renderPicks(); renderKpis(); renderExposure(); renderParlay(); }

let qTimer;
$("#q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(onFilter, 150); });
for (const sel of Object.values(ctl)) if (sel !== "#q") $(sel).addEventListener("change", onFilter);
$("#when").addEventListener("click", (e) => { const b = e.target.closest("button[data-w]"); if (b) { F.w = b.dataset.w; update(); } });
$("#fClear").addEventListener("click", () => { Object.assign(F, DEF, { w: F.w }); update(); });

function renderKpis() {
  if (!S) return;
  const ps = picks();
  const ev = ps.reduce((a, p) => a + p.exp_profit, 0), stake = ps.reduce((a, p) => a + p.stake, 0);
  const avgEdge = ps.length ? ps.reduce((a, p) => a + p.edge, 0) / ps.length : null;
  const t = S.track?.total || {}, roiTrack = trackRoi();
  const promoted = (S.learn?.log || []).filter((r) => r.promoted).length;
  const k = [
    ["Picks in view", ps.length, ps.length ? `avg win chance ${pct(ps.reduce((a, p) => a + p.fair, 0) / ps.length, 0)} · ${ps.filter((p) => p.confidence === "A").length} grade A` : "loosen the filters"],
    ["Expected profit", usd(ev, 2), "sum across picks"],
    ["Capital at work", usd(stake, 0), `${pct(stake / S.bankroll, 0)} of bankroll`],
    ["Avg edge after fee", pct(avgEdge, 1), "fair minus cost"],
    ["Track record", t.graded ? `${t.wins}-${t.graded - t.wins}` : "–", t.graded ? `won ${pct(t.wins / t.graded, 0)} · ROI ${pct(roiTrack, 1, true)} · ${t.pending} pending` : `${t.pending ?? 0} pending, none settled yet`],
    ["Model", promoted ? `${promoted} promoted` : "Champions held", "nightly, unseen games only"],
  ];
  $("#kpis").innerHTML = k.map(([a, b, c]) => `<div class="kpi"><span>${a}</span><b>${esc(b)}</b><small>${esc(c)}</small></div>`).join("");
}

function trackRoi() {
  const b = S.track?.buckets || [];
  const staked = b.reduce((a, r) => a + r.n * r.avg_price, 0);
  const pnl = b.reduce((a, r) => a + (r.roi ?? 0) * r.n * r.avg_price, 0);
  return staked ? pnl / staked : null;
}

function startsIn(iso) {
  if (!iso) return "–";
  const m = (Date.parse(iso) - Date.now()) / 60e3;
  if (m < 0) return "Live";
  const r = Math.round(m);
  if (r < 60) return `${r}m`;
  if (r < 48 * 60) return `${Math.floor(r / 60)}h ${r % 60}m`;
  return new Date(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

let lastPrices = new Map();
function renderPicks(flash = false) {
  if (!S) return;
  const ps = picks();
  $("#pickCount").textContent = ps.length ? `(${ps.length})` : "";
  $("#noPicks").hidden = ps.length > 0;
  $("#blotter tbody").innerHTML = ps.map((p, i) => {
    const before = lastPrices.get(p.ticker), moved = flash && before != null && before !== p.price;
    const cls = moved ? (p.price < before ? "tick-up" : "tick-down") : "";   // cheaper = better for us
    const tm = teamsOf(p).map((t) => `${t.rank ? `<span class="rk">#${t.rank}</span>` : ""}${esc(t.abbr || t.name)}${t.conf ? `<span class="cf">${esc(t.conf)}</span>` : ""}`).join(" @ ");
    return `<tr tabindex="0" data-t="${esc(p.ticker)}" class="${cls}">
      <td class="c">${p.game_id ? `<input type="checkbox" data-leg="${esc(p.ticker)}" ${legs.has(p.ticker) ? "checked" : ""} aria-label="Add to parlay">` : ""}</td>
      <td class="rank">${i + 1}</td>
      <td class="pick"><b><span class="tag">${esc(p.desk === "crypto" ? "CRYPTO" : p.league)}</span>${esc(p.title)}</b>
        <small>${tm ? tm + " · " : ""}Buy <span class="side-${p.side}">${p.side.toUpperCase()}</span> · ${p.count} contracts · ROI ${pct(p.roi, 1, true)}</small></td>
      <td class="r">${cents(p.price)}${p.live ? "" : '<small class="muted"> snap</small>'}</td>
      <td class="r ${p.fair >= WIN_MIN ? "pos" : ""}">${pct(p.fair, 0)}</td>
      <td class="r ${p.edge > 0 ? "pos" : "neg"}">${pct(p.edge, 1, true)}</td>
      <td class="c"><span class="grade ${esc(p.confidence)}" title="Confidence ${esc(p.confidence)}">${esc(p.confidence)}</span></td>
      <td class="r">${usd(p.stake, 2)}</td>
      <td class="r ${p.exp_profit > 0 ? "pos" : "neg"}">${usd(p.exp_profit, 2)}</td>
      <td class="r">${startsIn(p.start)}</td></tr>`;
  }).join("");
  lastPrices = new Map(ps.map((p) => [p.ticker, p.price]));
}

$("#blotter").addEventListener("change", (e) => { const t = e.target.dataset?.leg; if (t) toggleLeg(t, e.target.checked); });
$("#blotter").addEventListener("click", (e) => { if (e.target.dataset?.leg) return; const tr = e.target.closest("tr[data-t]"); if (tr) openPick(tr.dataset.t); });
$("#blotter").addEventListener("keydown", (e) => { const tr = e.target.closest("tr[data-t]"); if (tr && e.key === "Enter") openPick(tr.dataset.t); });

function openPick(ticker) {
  const p = reprice(S.picks.find((x) => x.ticker === ticker));
  const g = (S.games || []).find((x) => x.id === p.game_id);
  const m = g?.model || {};
  const notes = [...(m.notes || []), ...(m.injuries || []).map((x) => typeof x === "string" ? x : x.name || JSON.stringify(x))];
  $("#drawerBody").innerHTML = `
    <span class="tag">${esc(p.desk === "crypto" ? "CRYPTO" : p.league)}</span>
    <h3>${esc(p.title)}</h3>
    <div class="muted small mono">${esc(p.ticker)}</div>
    <div class="facts">
      <div><span>Buy</span><b class="side-${p.side}">${p.side.toUpperCase()} @ ${cents(p.price)}</b></div>
      <div><span>Our fair price</span><b>${cents(p.fair)}</b></div>
      <div><span>Edge after fee</span><b class="${p.edge > 0 ? "pos" : "neg"}">${pct(p.edge, 1, true)}</b></div>
      <div><span>Confidence</span><b>${esc(p.confidence)}</b></div>
      <div><span>Stake (¼ Kelly)</span><b>${usd(p.stake, 2)}</b></div>
      <div><span>Contracts</span><b>${p.count}</b></div>
      <div><span>ROI</span><b>${pct(p.roi, 1, true)}</b></div>
      <div><span>Expected profit</span><b>${usd(p.exp_profit, 2)}</b></div>
    </div>
    ${g ? `<p class="small muted">${esc(g.name)} · ${esc(g.venue || "")} · ${startsIn(g.start)}</p>
      <div class="facts">
        <div><span>Model margin</span><b>${m.margin ?? "–"}</b></div>
        <div><span>Book margin</span><b>${g.book?.margin?.toFixed?.(1) ?? "–"}</b></div>
        <div><span>Model total</span><b>${m.total ?? "–"}</b></div>
        <div><span>Book total</span><b>${g.book?.total?.toFixed?.(1) ?? "–"}</b></div>
      </div>
      ${notes.length ? `<ul>${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      ${m.weather ? `<p class="small muted">Weather: ${esc(typeof m.weather === "string" ? m.weather : JSON.stringify(m.weather))}</p>` : ""}` : ""}
    <p class="small muted">Segment ${esc(p.segment || "–")} · sizing multiplier ${p.segment_mult ?? 1}×. ${p.live ? "Price is live from Kalshi." : "Price is from the latest refresh, a few minutes old at most."}</p>`;
  $("#drawer").showModal();
}

// ---------- parlays ----------
// Legs must be from different games (same-game legs are correlated, so multiplying them would overstate the
// chance). Kalshi prices combos on request, so the page cannot read a live combo price: it gives the most
// you should accept instead, keeping a 2¢ cushion after the fee.
const pick = (t) => (S?.picks || []).map(reprice).find((p) => p.ticker === t);
function toggleLeg(t, on) {
  const p = pick(t);
  if (on && [...legs].some((x) => pick(x)?.game_id === p?.game_id)) { renderPicks(); return alert0("One leg per game: those outcomes move together."); }
  if (on && legs.size >= 4) { renderPicks(); return alert0("Four legs at most: each one cuts the chance to win."); }
  on ? legs.add(t) : legs.delete(t);
  renderParlay();
}
let note = "";
function alert0(m) { note = m; renderParlay(); }

function maxPrice(fair, cushion = 0.02) {
  for (let c = 99; c >= 1; c--) { const x = c / 100; if (fair - x - fee(x) >= cushion) return x; }
  return null;
}

function suggest() {
  const pool = (S?.picks || []).map(reprice).filter((p) => p.desk === "sports" && inWindow(p) && p.fair >= WIN_MIN && p.edge > 0)
    .sort((a, b) => b.fair / b.price - a.fair / a.price);
  const out = [], seen = new Set();
  for (const p of pool) { if (!seen.has(p.game_id)) { seen.add(p.game_id); out.push(p.ticker); } if (out.length === 2) break; }
  legs.clear(); out.forEach((t) => legs.add(t)); note = out.length < 2 ? "Not enough strong legs in this window for a parlay." : "";
  renderPicks(); renderParlay();
}
$("#pSuggest").addEventListener("click", suggest);
$("#parlay").addEventListener("click", (e) => { const t = e.target.dataset?.rm; if (t) { legs.delete(t); renderPicks(); renderParlay(); } });

function renderParlay() {
  const ls = [...legs].map(pick).filter(Boolean);
  if (ls.length !== legs.size) for (const t of [...legs]) if (!pick(t)) legs.delete(t);   // a leg dropped off the board
  if (!ls.length) {
    $("#parlay").innerHTML = `<p class="muted small" style="margin:0">${esc(note) || "Tick 2 or 3 bets from different games, or press Suggest best."}</p>`;
    return;
  }
  const win = ls.reduce((a, p) => a * p.fair, 1), mkt = ls.reduce((a, p) => a * p.price, 1), mx = maxPrice(win);
  const stake = S.max_trade, payout = mx ? stake / (mx + fee(mx)) : null;
  $("#parlay").innerHTML = `${ls.map((p) => `<div class="leg"><span>${esc(p.title)}</span><span class="mono">${pct(p.fair, 0)}
      <button class="link" data-rm="${esc(p.ticker)}" aria-label="Remove leg">×</button></span></div>`).join("")}
    <div class="big">
      <div><span>Chance all win</span><b class="${win >= 0.5 ? "pos" : "neg"}">${pct(win, 0)}</b></div>
      <div><span>Legs bought singly</span><b>${cents(mkt)}</b></div>
      <div><span>Accept combo at most</span><b>${mx ? cents(mx) : "skip"}</b></div>
    </div>
    <p class="small muted" style="margin:0">${mx ? `At ${cents(mx)}, ${usd(stake, 0)} returns about ${usd(payout, 2)} if every leg wins. ` : "No price leaves an edge after the fee. "}
      Kalshi quotes combos on request; take a quote only at or below this number. ${ls.length < 2 ? "Add another leg from a different game." : ""}
      ${win < 0.5 ? "Most parlays at this size lose: keep stakes small and judge them separately." : ""}</p>
    ${note ? `<p class="small" style="margin:0;color:var(--warn)">${esc(note)}</p>` : ""}`;
  note = "";
}

function renderExposure() {
  const by = {};
  for (const p of picks()) by[p.desk === "crypto" ? "Crypto" : p.league] = (by[p.desk === "crypto" ? "Crypto" : p.league] || 0) + p.stake;
  const rows = Object.entries(by).sort((a, b) => b[1] - a[1]), max = Math.max(1, ...rows.map((r) => r[1]));
  $("#exposure").innerHTML = rows.length ? rows.map(([k, v]) => `<div class="bar"><span>${esc(k)}</span>
    <div class="track" role="img" aria-label="${esc(k)} ${usd(v, 0)}"><div class="fill" style="width:${(v / max) * 100}%"></div></div>
    <span class="v">${usd(v, 0)}</span></div>`).join("") : `<p class="muted small" style="margin:0">No capital at work.</p>`;
}

function spark(points) {
  if (!points?.length) return "";
  const ys = points.map((p) => p[1]), lo = Math.min(...ys), hi = Math.max(...ys), n = ys.length;
  const d = ys.map((y, i) => `${i ? "L" : "M"}${((i / (n - 1)) * 300).toFixed(1)},${(40 - ((y - lo) / (hi - lo || 1)) * 36 + 2).toFixed(1)}`).join("");
  return `<svg viewBox="0 0 300 44" preserveAspectRatio="none" role="img" aria-label="One-year price, low ${usd(lo)} high ${usd(hi)}"><path d="${d}"/></svg>`;
}

function renderCrypto() {
  const c = S.crypto || {};
  const keys = Object.keys(c);
  $("#crypto").innerHTML = keys.length ? keys.map((k) => {
    const x = c[k], trend = x.sma50 && x.sma200 ? (x.sma50 > x.sma200 ? "Uptrend" : "Downtrend") : "–";
    const best = (x.strategies || []).filter((s) => s.id !== "buy_hold" && s.out_of_sample?.sharpe != null)
      .sort((a, b) => b.out_of_sample.sharpe - a.out_of_sample.sharpe)[0];
    return `<div class="coin"><div class="row"><b>${esc(k.split("-")[0])}</b><span class="px">${usd(x.spot, 0)}</span></div>
      ${spark((x.chart || []).slice(-365))}
      <div class="stats">
        <div><span>Trend</span><b class="${trend === "Uptrend" ? "pos" : "neg"}">${trend}</b></div>
        <div><span>Vol (ann.)</span><b>${pct(x.vol_annual, 0)}</b></div>
        <div><span>RSI 14</span><b>${x.rsi14?.toFixed?.(0) ?? "–"}</b></div>
      </div>
      ${best ? `<p class="small muted" style="margin:8px 0 0">Best trend rule: ${esc(best.name)}, Sharpe ${best.out_of_sample.sharpe.toFixed(2)} on unseen data, position ${pct(best.position, 0)}</p>` : ""}
    </div>`;
  }).join("") : `<p class="muted small" style="padding:0 16px 14px;margin:0">Crypto data unavailable this run.</p>`;
}

function renderHealth() {
  const log = S.learn?.log || [], last = {};
  for (const r of log) last[r.league] = r;
  const rows = Object.values(last);
  $("#health").innerHTML = `<div class="health">${rows.length ? rows.map((r) => `<div class="row">
      <span><i class="dot ${r.promoted ? "ok" : ""}"></i>${esc(String(r.league).toUpperCase())}</span>
      <span class="muted small">${r.promoted ? "New model promoted" : esc(r.reason || "Champion kept")}</span></div>`).join("")
    : `<span class="muted small">Nightly learning runs after 4 AM Central. First results appear tomorrow.</span>`}
    <div class="row small muted"><span>Ratings fitted on</span><span class="mono">${Object.entries(S.ratings_n || {}).map(([k, v]) => `${esc(k)} ${v}`).join(" · ") || "–"}</span></div></div>`;
}

function renderSlate() {
  const gs = (S.games || []).filter((g) => g.state === "pre").slice(0, 60);
  const f1 = (v) => v == null ? "–" : (+v).toFixed(1);
  $("#slate tbody").innerHTML = gs.length ? gs.map((g) => `<tr><td>${esc(g.name)}</td><td>${esc(g.league)}</td>
    <td class="r">${startsIn(g.start)}</td><td class="r">${f1(g.model?.blend_margin)}</td><td class="r">${f1(g.book?.margin)}</td>
    <td class="r">${f1(g.model?.blend_total)}</td><td class="r">${f1(g.book?.total)}</td>
    <td class="muted small">${esc([...(g.model?.notes || [])].slice(0, 2).join("; "))}</td></tr>`).join("")
    : `<tr><td colspan="8" class="muted">No upcoming games with Kalshi markets.</td></tr>`;
}

function renderTrack() {
  const t = S.track?.total || {}, b = S.track?.buckets || [];
  const head = `<div class="trackhead">
    <div><span>Graded</span><b>${t.graded ?? 0}</b></div>
    <div><span>Hit rate</span><b>${t.graded ? pct(t.wins / t.graded, 1) : "–"}</b></div>
    <div><span>ROI</span><b class="${(trackRoi() ?? 0) >= 0 ? "pos" : "neg"}">${pct(trackRoi(), 1, true)}</b></div>
    <div><span>Pending</span><b>${t.pending ?? 0}</b></div></div>`;
  const table = b.length ? `<div class="tablewrap"><table><thead><tr><th>League</th><th>Market</th><th>Edge bucket</th>
    <th class="r">Bets</th><th class="r">Hit</th><th class="r">Avg fair</th><th class="r">Avg price</th><th class="r">ROI</th><th class="r">CLV</th></tr></thead><tbody>
    ${b.map((r) => `<tr><td>${esc(r.league)}</td><td>${esc(r.kind)}</td><td>${esc(r.bucket)}</td><td class="r">${r.n}</td>
      <td class="r">${pct(r.hit, 1)}</td><td class="r">${cents(r.avg_fair)}</td><td class="r">${cents(r.avg_price)}</td>
      <td class="r ${(r.roi ?? 0) >= 0 ? "pos" : "neg"}">${pct(r.roi, 1, true)}</td><td class="r">${r.clv == null ? "–" : pct(r.clv, 1, true)}</td></tr>`).join("")}
    </tbody></table></div>` : `<p class="empty">No graded picks yet. Results fill in as Kalshi settles each market.</p>`;
  $("#track").innerHTML = head + table;
}

// ---------- theme ----------
(function theme() {
  let saved = null;
  try { saved = localStorage.getItem("kil-theme"); } catch {}
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme").onclick = () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("kil-theme", document.documentElement.dataset.theme); } catch {}
  };
})();

loadUrl();
pullState();
setInterval(pullState, STATE_EVERY);
setInterval(() => { setFeed(); if (S) renderPicks(); }, 30e3);   // keep countdowns fresh
