// Kil Capital Terminal: static dashboard. Reads data/state.json (rebuilt by GitHub Actions every few minutes)
// and, where the browser is allowed to, refreshes prices straight from Kalshi's public market data so
// edges and stakes stay live between rebuilds. Recommend-only: nothing here can place an order.
"use strict";

const KALSHI = "https://api.elections.kalshi.com/trade-api/v2";
const STATE_EVERY = 60e3,
  LIVE_EVERY = 15e3,
  LIVE_RETRY = 300e3,
  STALE_MIN = 30;
const $ = (s) => document.querySelector(s);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const usd = (v, d = 0) =>
  v == null
    ? "–"
    : (v < 0 ? "−$" : "$") +
      Math.abs(v).toLocaleString(undefined, {
        minimumFractionDigits: d,
        maximumFractionDigits: d,
      });
const cents = (p) => (p == null ? "–" : Math.round(p * 100) + "¢");
const pct = (v, d = 1, sign = false) =>
  v == null ? "–" : (sign && v > 0 ? "+" : "") + (v * 100).toFixed(d) + "%";
const fee = (p) => 0.07 * p * (1 - p);

let S = null,
  liveOk = null,
  liveTimer = null;
const TZ = "America/Chicago",
  WIN_MIN = 0.55;
const F = {
  w: "today",
  q: "",
  league: "",
  conf: "",
  kind: "",
  grade: "",
  top25: false,
  rvr: false,
  win: true,
  sort: "profit",
};
const legs = new Set(); // tickers ticked for the parlay
const quotes = new Map(); // ticker -> {yes, no} live asks

// ---------- your bankroll (saved in this browser only) ----------
const UKEY = "kil-bankroll";
function U() {
  let u = {};
  try {
    u = JSON.parse(localStorage.getItem(UKEY) || "{}");
  } catch {}
  return {
    bankroll: +u.bankroll || S?.bankroll || 100,
    budget: u.budget != null && u.budget !== "" ? +u.budget : (S?.budget ?? 25),
    max: +u.max || S?.max_trade || 3,
    open: +u.open || 0,
  };
}
function saveU(u) {
  try {
    localStorage.setItem(UKEY, JSON.stringify(u));
  } catch {}
}

// ---------- sizing (mirrors sports/segments.size and budget.allocate) ----------
function size(fair, price, bank, maxT, mult = 1) {
  const c = price + fee(price),
    f = c < 1 ? Math.max(0, (fair - c) / (1 - c)) : 0;
  const st = Math.min(maxT, (S.kelly_fraction ?? 0.25) * f * mult * bank),
    count = c > 0 ? Math.floor(st / c + 1e-9) : 0;
  return {
    count,
    stake: +(count * c).toFixed(2),
    roi: (fair - c) / c,
    exp_profit: +(count * (fair - c)).toFixed(2),
  };
}
function reprice(p) {
  const q = quotes.get(p.ticker),
    lp = q ? q[p.side] : null;
  const live = lp != null && lp > 0 && lp < 1,
    price = live ? lp : p.price;
  return {
    ...p,
    live,
    prev: p.price,
    price,
    edge: p.fair - price - fee(price),
  };
}
// Favourites (55%+) first, best expected profit first within each; fill until the budget is used.
function plan() {
  if (!S) return [];
  const u = U();
  let left = Math.max(0, u.budget - u.open);
  const ps = (S.picks || [])
    .map(reprice)
    .map((p) => ({
      ...p,
      full: size(p.fair, p.price, u.bankroll, u.max, p.segment_mult ?? 1),
    }))
    .sort(
      (a, b) =>
        (a.fair < WIN_MIN) - (b.fair < WIN_MIN) ||
        b.full.exp_profit - a.full.exp_profit ||
        b.edge - a.edge,
    );
  return ps.map((p) => {
    const sz = size(
        p.fair,
        p.price,
        u.bankroll,
        Math.min(u.max, left),
        p.segment_mult ?? 1,
      ),
      take = sz.count >= 1 && p.edge > 0 && !(F.win && p.fair < WIN_MIN);
    if (take) left -= sz.stake;
    return {
      ...p,
      slate: take,
      count: take ? sz.count : 0,
      stake: take ? sz.stake : 0,
      exp_profit: take ? sz.exp_profit : 0,
      roi: p.full.roi,
    };
  });
}

const ymd = (t) => new Date(t).toLocaleDateString("en-CA", { timeZone: TZ });
const teamsOf = (p) => p.teams || [];
const ranked = (p) => teamsOf(p).filter((t) => t.rank).length;

function inWindow(p) {
  if (!p.start) return true; // crypto: always open
  const t = Date.parse(p.start),
    now = Date.now();
  if (F.w === "today") return t < now || ymd(t) === ymd(now); // started counts as today
  if (F.w === "tomorrow") return ymd(t) === ymd(now + 864e5);
  if (F.w === "weekend") {
    // this Fri-Sun in Central time; on Fri-Sun that includes games already started today
    const dow = new Date(now).toLocaleDateString("en-US", { timeZone: TZ, weekday: "short" });
    const toSun = { Mon: 6, Tue: 5, Wed: 4, Thu: 3, Fri: 2, Sat: 1, Sun: 0 }[dow];
    const days = new Set([0, 1, 2].map((d) => ymd(now + (toSun - d) * 864e5)));
    return days.has(ymd(t)) && (t > now - 6 * 36e5 || ymd(t) === ymd(now));
  }
  return t < now + 7 * 864e5;
}

function matches(p) {
  if (!inWindow(p)) return false;
  if (F.league && (p.desk === "crypto" ? "Crypto" : p.league) !== F.league)
    return false;
  if (F.kind && p.kind !== F.kind) return false;
  if (F.grade && !F.grade.includes(p.confidence)) return false;
  if (F.conf && !teamsOf(p).some((t) => t.conf === F.conf)) return false;
  if (F.top25 && !ranked(p)) return false;
  if (F.rvr && ranked(p) < 2) return false;
  if (F.win && !(p.fair >= WIN_MIN && p.edge > 0)) return false;
  if (F.q) {
    const hay = [
      p.title,
      ...teamsOf(p).flatMap((t) => [t.name, t.abbr, t.nick]),
    ]
      .join(" ")
      .toLowerCase();
    if (
      !F.q
        .toLowerCase()
        .split(/\s+/)
        .every((w) => hay.includes(w))
    )
      return false;
  }
  return true;
}

const SORTS = {
  profit: (a, b) =>
    b.slate - a.slate ||
    b.exp_profit - a.exp_profit ||
    b.full.exp_profit - a.full.exp_profit,
  win: (a, b) => b.fair - a.fair,
  edge: (a, b) => (b.edge ?? -1) - (a.edge ?? -1),
  start: (a, b) => ((a.start || "9") < (b.start || "9") ? -1 : 1),
};
// "Rank, then time": on-slate bets first, then by start time
SORTS.ranktime = (a, b) => b.slate - a.slate || SORTS.start(a, b);
function picks() {
  const ps = plan().filter(matches),
    seen = new Set(ps.map((p) => p.game_id).filter(Boolean));
  const cs = gameCalls().filter((c) => !seen.has(c.game_id) && callMatches(c));
  return ps.concat(cs).sort(SORTS[F.sort] || SORTS.profit);
}
// Every game gets a pick: the best side we can find (or, once a game has started, our pre-game winner),
// with a confidence level. These calls never enter plan(), the budget or the Autotracker.
function callFor(g) {
  const teams = ["away", "home"].map((s) => ({
    name: g[s]?.name, abbr: g[s]?.abbr, nick: g[s]?.nick, rank: g[s]?.rank, conf: g[s]?.conf,
  }));
  const base = { desk: "sports", league: g.league, game_id: g.id, start: g.start, teams, call: true,
    slate: false, count: 0, stake: 0, exp_profit: 0, full: { exp_profit: 0 }, segment_mult: 1 };
  if (g.state !== "pre") {
    const w = (g.contracts || []).find((c) => c.kind === "winner" && c.p_fair != null);
    if (!w) return null;
    const yes = w.p_fair >= 0.5;
    return { ...base, ticker: w.ticker, kind: "winner", side: yes ? "yes" : "no", price: null,
      fair: yes ? w.p_fair : 1 - w.p_fair, edge: null, roi: null, confidence: w.confidence || "C",
      level: "live", title: `${g.name}: ${betLabel(g, w)} ${yes ? "YES" : "NO"}` };
  }
  const rs = ["winner", "spread", "total"]
    .map((k) => boardRow(g, k, new Set()))
    .filter((r) => r && r.b.price >= 0.1 && r.b.price <= 0.92);
  if (!rs.length) return null;
  const r = rs.reduce((a, b) => (b.b.edge > a.b.edge ? b : a)),
    cost = r.b.price + fee(r.b.price);
  return { ...base, ticker: r.c.ticker, kind: r.c.kind, side: r.b.side, price: r.b.price, fair: r.b.fair,
    edge: r.b.edge, roi: cost > 0 ? (r.b.fair - cost) / cost : null, confidence: r.c.confidence || "C",
    level: r.b.edge > 0 ? "lean" : "low", title: `${g.name}: ${betLabel(g, r.c)} ${r.b.side.toUpperCase()}` };
}
function gameCalls() {
  return (S?.games || []).filter((g) => g.state !== "post").map(callFor).filter(Boolean);
}
function callMatches(c) {
  const win = F.win;
  F.win = false; // win-majority only gates bets that clear the bar; every game still gets a call
  try { return matches(c); } finally { F.win = win; }
}
// All rows the page can show, so a click or a parlay leg finds a call as well as a bet.
function allRows() {
  const ps = plan(), seen = new Set(ps.map((p) => p.ticker));
  return ps.concat(gameCalls().filter((c) => !seen.has(c.ticker)));
}
const LV = { high: "High", medium: "Medium", lean: "Lean", low: "Low", live: "Live" };
function level(p) {
  if (p.call) return p.level;
  if (p.slate) return p.confidence === "C" ? "medium" : "high";
  return p.edge > 0 ? "lean" : "low";
}
const LV_WHY = {
  high: "Clears every check, and the data behind it is solid.",
  medium: "Clears every check, but thin data or a wide Kalshi spread makes it less certain.",
  lean: "Our model likes this side a little, but not enough to clear the bar after Kalshi's fee.",
  low: "Our best side for this game, but there is no edge after Kalshi's fee. Treat it as a coin-flip-level call.",
  live: "Game in progress. This is our pre-game winner call; Kalshi's live price already reflects the score.",
};

async function pullLive() {
  const tickers = [...new Set((S?.picks || []).map((p) => p.ticker))];
  if (!tickers.length) return;
  try {
    for (let i = 0; i < tickers.length; i += 50) {
      const r = await fetch(
        `${KALSHI}/markets?tickers=${encodeURIComponent(tickers.slice(i, i + 50).join(","))}&limit=100`,
        { cache: "no-store" },
      );
      if (!r.ok) throw new Error(r.status);
      for (const m of (await r.json()).markets || []) {
        const px = (k) =>
          m[`${k}_dollars`] != null
            ? +m[`${k}_dollars`]
            : m[k] != null
              ? m[k] / 100
              : null;
        quotes.set(m.ticker, { yes: px("yes_ask"), no: px("no_ask") });
      }
    }
    liveOk = true;
  } catch {
    liveOk = false; // blocked (CORS) or offline: fall back to the 15-minute snapshot
  }
  setFeed();
  renderPicks(true);
  renderKpis();
  renderPlan();
  renderCryptoBets();
  clearTimeout(liveTimer);
  liveTimer = setTimeout(pullLive, liveOk ? LIVE_EVERY : LIVE_RETRY);
}

// ---------- state ----------
async function pullState() {
  try {
    const r = await fetch(`data/state.json?t=${Date.now()}`, {
      cache: "no-store",
    });
    if (!r.ok) throw new Error(r.status);
    S = await r.json();
    render();
    if (liveOk === null) pullLive();
  } catch (e) {
    if (!S)
      (($("#noPicks").hidden = false),
        ($("#noPicks").textContent =
          "Waiting for the first refresh from GitHub Actions."));
  }
  setFeed();
}

function ageMin() {
  return S ? (Date.now() - Date.parse(S.generated)) / 60e3 : Infinity;
}

function setFeed() {
  const el = $("#feed"),
    lab = $("#feedLabel"),
    a = ageMin();
  el.className = "feed " + (a > STALE_MIN ? "stale" : liveOk ? "live" : "snap");
  lab.textContent =
    a > STALE_MIN ? "Stale" : liveOk ? "Live prices" : "Auto-refreshing";
  const up = $("#updated");
  up.textContent = !S
    ? "–"
    : a > STALE_MIN
      ? `Data is ${Math.round(a)} min old`
      : `Models ${a < 1 ? "just now" : Math.round(a) + " min ago"}`;
  up.style.color = S && a > STALE_MIN ? "var(--neg)" : "";
}

// ---------- render ----------
function render() {
  $("#bankroll").textContent = usd(U().bankroll);
  renderSettings();
  renderFilters();
  renderKpis();
  renderPlan();
  renderPicks();
  renderExposure();
  renderParlay();
  renderCrypto();
  renderCryptoBets();
  renderHealth();
  renderBoard();
  renderTop5();
  renderSlate();
  renderTrack();
  renderAuto();
  renderLearn();
  window.renderLive?.(); // live.js: in-game model (Live tab)
  const errs = S.errors || [];
  $("#errors").hidden = !errs.length;
  $("#errors").textContent = errs.length
    ? "Data notes: " + errs.join(" · ")
    : "";
}

const ctl = {
  q: "#q",
  conf: "#fConf",
  kind: "#fKind",
  grade: "#fGrade",
  top25: "#fTop25",
  rvr: "#fRvR",
  win: "#fWin",
  sort: "#fSort",
};
const DEF = { ...F };

const VIEWS = ["board", "live", "results", "crypto", "ledger", "learn", "how"];
let TAB = "board";
function loadUrl() {
  const u = new URLSearchParams(location.search);
  const v = { picks: "board", auto: "ledger" }[u.get("view")] || u.get("view");
  TAB = VIEWS.includes(v) ? v : "board";
  Object.assign(F, DEF);
  for (const k of Object.keys(F))
    if (u.has(k))
      F[k] = typeof DEF[k] === "boolean" ? u.get(k) === "1" : u.get(k);
}
function saveUrl(push = false) {
  const u = new URLSearchParams();
  if (TAB !== "board") u.set("view", TAB);
  for (const [k, v] of Object.entries(F))
    if (v !== DEF[k]) u.set(k, typeof v === "boolean" ? (v ? "1" : "0") : v);
  const url = u.toString() ? "?" + u : location.pathname;
  if (push) history.pushState(null, "", url);
  else history.replaceState(null, "", url);
}

function options(sel, vals, all) {
  const cur = F[Object.keys(ctl).find((k) => ctl[k] === sel)];
  $(sel).innerHTML =
    `<option value="">${all}</option>` +
    vals
      .map((v) => `<option${v === cur ? " selected" : ""}>${esc(v)}</option>`)
      .join("");
}

function renderFilters() {
  const ps = S.picks || [];
  // sport chips: every league with a pick or a game, in a fixed order
  const ORDER = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "WNBA"];
  const lg = [
    ...new Set([
      ...ps.map((p) => (p.desk === "crypto" ? "Crypto" : p.league)),
      ...(S.games || []).map((g) => g.league),
    ]),
  ]
    .filter(Boolean)
    .sort((a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99) || (a < b ? -1 : 1));
  if (F.league && !lg.includes(F.league)) lg.push(F.league);
  $("#sports").innerHTML = ["", ...lg]
    .map(
      (l) =>
        `<button data-l="${esc(l)}" aria-pressed="${F.league === l}">${l ? esc(l) : "All sports"}</button>`,
    )
    .join("");
  options(
    "#fConf",
    [
      ...new Set(
        ps.flatMap((p) => teamsOf(p).map((t) => t.conf)).filter(Boolean),
      ),
    ].sort(),
    "All conferences",
  );
  for (const [k, sel] of Object.entries(ctl)) {
    const el = $(sel);
    if (el.type === "checkbox") el.checked = F[k];
    else el.value = F[k];
  }
  for (const b of document.querySelectorAll("#when button"))
    b.setAttribute("aria-pressed", b.dataset.w === F.w);
  const n = Object.keys(F).filter(
    (k) => !["w", "sort", "q", "league"].includes(k) && F[k] !== DEF[k],
  ).length;
  $("#fCount").textContent = n ? `(${n})` : "";
}

function onFilter() {
  for (const [k, sel] of Object.entries(ctl)) {
    const el = $(sel);
    F[k] = el.type === "checkbox" ? el.checked : el.value;
  }
  update();
}
function update() {
  saveUrl();
  renderFilters();
  renderPicks();
  renderKpis();
  renderPlan();
  renderExposure();
  renderParlay();
  renderCryptoBets();
  renderBoard();
  renderTop5();
  window.renderLive?.();
}

let qTimer;
$("#q").addEventListener("input", () => {
  clearTimeout(qTimer);
  qTimer = setTimeout(onFilter, 150);
});
for (const sel of Object.values(ctl))
  if (sel !== "#q") $(sel).addEventListener("change", onFilter);
$("#when").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-w]");
  if (b) {
    F.w = b.dataset.w;
    update();
  }
});
$("#fClear").addEventListener("click", () => {
  Object.assign(F, DEF, { w: F.w, league: F.league, q: F.q, sort: F.sort });
  update();
});
$("#sports").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-l]");
  if (b) {
    F.league = b.dataset.l;
    update();
  }
});

// ---------- Top 5 ----------
function renderTop5() {
  if (!S) return;
  const ps = picks()
    .filter((p) => p.slate)
    .slice(0, 5);
  $("#top5").innerHTML = ps.length
    ? ps
        .map(
          (p, i) => `<button class="card" data-t="${esc(p.ticker)}">
      <span class="cardtop"><span class="tag">${esc(p.desk === "crypto" ? "CRYPTO" : p.league)}</span><span class="muted small">#${i + 1} · ${startsIn(p.start || p.close)}</span></span>
      <b>${esc(p.title)}</b>
      <span class="small">${p.desk === "crypto" ? esc(cryptoAction(p)) : `Buy <span class="side-${p.side}">${p.side.toUpperCase()}</span> at ${cents(p.price)}`}</span>
      <span class="cardnums"><span><small>Win</small>${pct(p.fair, 0)}</span><span><small>Edge</small><i class="pos">${pct(p.edge, 1, true)}</i></span><span><small>Stake</small>${usd(p.stake, 2)}</span></span>
    </button>`,
        )
        .join("")
    : `<p class="empty">No bet clears the bar for this sport and day. Every game below still has our call.</p>`;
}
$("#top5").addEventListener("click", (e) => {
  const c = e.target.closest("[data-t]");
  if (c) openPick(c.dataset.t);
});

function renderKpis() {
  if (!S) return;
  const ps = picks(),
    all = plan(),
    on = all.filter((p) => p.slate); // slate KPIs match "Your slate", not the table filters
  const ev = on.reduce((a, p) => a + p.exp_profit, 0),
    stake = on.reduce((a, p) => a + p.stake, 0);
  const ed = ps.filter((p) => p.edge != null);
  const avgEdge = ed.length
    ? ed.reduce((a, p) => a + p.edge, 0) / ed.length
    : null;
  const t = S.track?.total || {},
    roiTrack = trackRoi();
  const promoted = (S.learn?.log || []).filter((r) => r.promoted).length;
  const k = [
    [
      "Bets on your slate",
      on.length,
      on.length
        ? `avg win chance ${pct(on.reduce((a, p) => a + p.fair, 0) / on.length, 0)} · ${all.length - on.length} watch-only`
        : "nothing clears the bar",
    ],
    ["Expected profit", usd(ev, 2), "sum across your slate"],
    [
      "Capital at work",
      usd(stake, 2),
      `${pct(stake / U().bankroll, 0)} of your bankroll · budget ${usd(U().budget)}`,
    ],
    ["Avg edge after fee", pct(avgEdge, 1), "fair minus cost"],
    [
      "Track record",
      t.graded ? `${t.wins}-${t.graded - t.wins}` : "–",
      t.graded
        ? `won ${pct(t.wins / t.graded, 0)} · ROI ${pct(roiTrack, 1, true)} · ${t.pending} pending`
        : `${t.pending ?? 0} pending, none settled yet`,
    ],
    [
      "Model",
      promoted ? `${promoted} promoted` : "Champions held",
      "nightly, unseen games only",
    ],
  ];
  $("#kpis").innerHTML = k
    .map(
      ([a, b, c]) =>
        `<div class="kpi"><span>${a}</span><b>${esc(b)}</b><small>${esc(c)}</small></div>`,
    )
    .join("");
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
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

let lastPrices = new Map();
function renderPicks(flash = false) {
  if (!S) return;
  const ps = picks();
  $("#pickCount").textContent = ps.length ? `(${ps.length})` : "";
  $("#noPicks").hidden = ps.length > 0;
  $("#blotter tbody").innerHTML = ps
    .map((p, i) => {
      const before = lastPrices.get(p.ticker),
        moved = flash && before != null && before !== p.price;
      const cls = moved ? (p.price < before ? "tick-up" : "tick-down") : ""; // cheaper = better for us
      const tm = teamsOf(p)
        .map(
          (t) =>
            `${t.rank ? `<span class="rk">#${t.rank}</span>` : ""}${esc(t.abbr || t.name)}${t.conf ? `<span class="cf">${esc(t.conf)}</span>` : ""}`,
        )
        .join(" @ ");
      return `<tr tabindex="0" data-t="${esc(p.ticker)}" class="${cls}${p.slate ? "" : " watch"}">
      <td class="c">${p.game_id && p.price != null ? `<input type="checkbox" data-leg="${esc(p.ticker)}" ${legs.has(p.ticker) ? "checked" : ""} aria-label="Add to parlay">` : ""}</td>
      <td class="rank">${i + 1}</td>
      <td class="pick"><b><span class="tag">${esc(p.desk === "crypto" ? "CRYPTO" : p.league)}</span>${esc(p.title)}</b>
        <small>${tm ? tm + " · " : ""}${p.desk === "crypto" ? esc(cryptoAction(p)) : `Buy <span class="side-${p.side}">${p.side.toUpperCase()}</span>`} · ${p.slate ? `${p.count} contracts` : p.call ? "our call, below the bar" : "watch only"}${p.roi != null ? ` · ROI ${pct(p.roi, 1, true)}` : ""}</small></td>
      <td class="r">${cents(p.price)}${p.live || p.price == null ? "" : '<small class="muted"> snap</small>'}</td>
      <td class="r ${p.fair >= WIN_MIN ? "pos" : ""}">${pct(p.fair, 0)}</td>
      <td class="r ${p.edge == null ? "muted" : p.edge > 0 ? "pos" : "neg"}">${pct(p.edge, 1, true)}</td>
      <td class="c"><span class="lvl ${level(p)}" title="${esc(LV_WHY[level(p)])} Data grade ${esc(p.confidence)}.">${LV[level(p)]}</span></td>
      <td class="r">${p.slate ? usd(p.stake, 2) : `<span class="muted">${p.call ? "your call" : "watch"}</span>`}</td>
      <td class="r ${p.exp_profit > 0 ? "pos" : ""}">${p.slate ? usd(p.exp_profit, 2) : "–"}</td>
      <td class="r">${startsIn(p.start || p.close)}</td></tr>`;
    })
    .join("");
  lastPrices = new Map(ps.map((p) => [p.ticker, p.price]));
}

$("#blotter").addEventListener("change", (e) => {
  const t = e.target.dataset?.leg;
  if (t) toggleLeg(t, e.target.checked);
});
$("#blotter").addEventListener("click", (e) => {
  if (e.target.dataset?.leg) return;
  const tr = e.target.closest("tr[data-t]");
  if (tr) openPick(tr.dataset.t);
});
$("#blotter").addEventListener("keydown", (e) => {
  const tr = e.target.closest("tr[data-t]");
  if (tr && e.key === "Enter") openPick(tr.dataset.t);
});

function openPick(ticker) {
  const p = allRows().find((x) => x.ticker === ticker);
  if (!p) return;
  const g = (S.games || []).find((x) => x.id === p.game_id);
  const m = g?.model || {};
  const notes = [
    ...(m.notes || []),
    ...(m.injuries || []).map((x) =>
      typeof x === "string" ? x : x.name || JSON.stringify(x),
    ),
  ];
  $("#drawerBody").innerHTML = `
    <span class="tag">${esc(p.desk === "crypto" ? "CRYPTO" : p.league)}</span>
    <h3>${esc(p.title)}</h3>
    <div class="muted small mono">${esc(p.ticker)}</div>
    ${p.desk === "crypto" ? `<p><b>${esc(cryptoAction(p))}</b></p>` : ""}
    <div class="facts">
      <div><span>Buy</span><b class="side-${p.side}">${p.side.toUpperCase()} @ ${cents(p.price)}</b></div>
      <div><span>Our fair price</span><b>${cents(p.fair)}</b></div>
      <div><span>Edge after fee</span><b class="${p.edge > 0 ? "pos" : "neg"}">${pct(p.edge, 1, true)}</b></div>
      <div><span>Confidence</span><b>${LV[level(p)]} <small class="muted">(data ${esc(p.confidence)})</small></b></div>
      <div><span>Stake</span><b>${p.slate ? usd(p.stake, 2) : "watch only"}</b></div>
      <div><span>Contracts</span><b>${p.count}</b></div>
      <div><span>ROI</span><b>${pct(p.roi, 1, true)}</b></div>
      <div><span>Expected profit</span><b>${usd(p.exp_profit, 2)}</b></div>
    </div>
    ${
      g
        ? `<p class="small muted">${esc(g.name)} · ${esc(g.venue || "")} · ${startsIn(g.start)}</p>
      <div class="facts">
        <div><span>Model margin</span><b>${m.margin ?? "–"}</b></div>
        <div><span>Book margin</span><b>${g.book?.margin?.toFixed?.(1) ?? "–"}</b></div>
        <div><span>Model total</span><b>${m.total ?? "–"}</b></div>
        <div><span>Book total</span><b>${g.book?.total?.toFixed?.(1) ?? "–"}</b></div>
      </div>
      ${notes.length ? `<ul>${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      ${m.weather ? `<p class="small muted">Weather: ${esc(typeof m.weather === "string" ? m.weather : JSON.stringify(m.weather))}</p>` : ""}`
        : ""
    }
    <p class="small">${esc(LV_WHY[level(p)])}</p>
    ${p.slate || p.call ? "" : `<p class="small muted">Not on your slate: your budget is already used by stronger picks, the win chance is under 55%, or the bet is too small to buy one contract.</p>`}
    ${p.call ? `<p class="small muted">Below the bar, so the model suggests no stake. If you bet it anyway, keep it to a small amount.</p>` : ""}
    <p class="small muted">Segment ${esc(p.segment || "–")} · sizing multiplier ${p.segment_mult ?? 1}×. ${p.live ? "Price is live from Kalshi." : "Price is from the latest refresh, a few minutes old at most."}</p>`;
  $("#drawer").showModal();
}

// ---------- parlays ----------
// Legs must be from different games (same-game legs are correlated, so multiplying them would overstate the
// chance). Kalshi prices combos on request, so the page cannot read a live combo price: it gives the most
// you should accept instead, keeping a 2¢ cushion after the fee.
const pick = (t) => allRows().find((p) => p.ticker === t);
function toggleLeg(t, on) {
  const p = pick(t);
  if (on && [...legs].some((x) => pick(x)?.game_id === p?.game_id)) {
    renderPicks();
    return alert0("One leg per game: those outcomes move together.");
  }
  if (on && legs.size >= 4) {
    renderPicks();
    return alert0("Four legs at most: each one cuts the chance to win.");
  }
  on ? legs.add(t) : legs.delete(t);
  renderParlay();
}
let note = "";
function alert0(m) {
  note = m;
  renderParlay();
}

function maxPrice(fair, cushion = 0.02) {
  for (let c = 99; c >= 1; c--) {
    const x = c / 100;
    if (fair - x - fee(x) >= cushion) return x;
  }
  return null;
}

// Ready-made parlays: at least 5, built from every game's pick (bets that clear the bar first, then our
// calls), one leg per game. Ranked by the chance every leg wins, with fair-priced combos first.
const LV_RANK = { high: 0, medium: 1, lean: 2, low: 3, live: 4 };
const legScore = (p) => p.fair + 2 * (p.edge ?? 0) + (p.slate ? 0.05 : 0);
let IDEAS = [];
function parlayIdeas(want = 6) {
  const byGame = new Map();
  for (const p of allRows()) {
    if (p.desk !== "sports" || !p.game_id || p.price == null || !inWindow(p)) continue;
    if (F.league && p.league !== F.league) continue;
    const cur = byGame.get(p.game_id);
    if (!cur || legScore(p) > legScore(cur)) byGame.set(p.game_id, p);
  }
  const pool = [...byGame.values()].sort((a, b) => legScore(b) - legScore(a)).slice(0, 12);
  const combos = [];
  for (let i = 0; i < pool.length; i++)
    for (let j = i + 1; j < pool.length; j++) {
      combos.push([pool[i], pool[j]]);
      for (let k = j + 1; k < pool.length; k++) combos.push([pool[i], pool[j], pool[k]]);
    }
  const rated = combos
    .map((ls) => {
      const win = ls.reduce((a, p) => a * p.fair, 1),
        mkt = ls.reduce((a, p) => a * p.price, 1),
        lv = ls.map(level).sort((a, b) => LV_RANK[b] - LV_RANK[a])[0];
      return { ls, win, mkt, lv, fairPriced: win >= mkt, mx: maxPrice(win) };
    })
    .sort((a, b) => b.fairPriced - a.fairPriced || b.win - a.win);
  // variety: a leg goes in at most two ideas, unless that leaves fewer than `want`
  const out = [],
    used = new Map();
  for (const cap of [2, Infinity])
    for (const x of rated) {
      if (out.length >= want) break;
      if (out.includes(x) || x.ls.some((p) => (used.get(p.ticker) || 0) >= cap)) continue;
      out.push(x);
      x.ls.forEach((p) => used.set(p.ticker, (used.get(p.ticker) || 0) + 1));
    }
  return out;
}
function renderIdeas() {
  IDEAS = S ? parlayIdeas() : [];
  $("#pIdeas").innerHTML = IDEAS.length
    ? IDEAS.map(
        (x, i) => `<button class="idea" data-i="${i}">
      <span class="ih"><b>Parlay ${i + 1} · ${x.ls.length} legs</b><span class="lvl ${x.lv}" title="${esc(LV_WHY[x.lv])}">${LV[x.lv]}</span></span>
      ${x.ls.map((p) => `<span class="il">${esc(p.title)} <span class="muted">${p.side.toUpperCase()} ${cents(p.price)} · ${pct(p.fair, 0)}</span></span>`).join("")}
      <span class="in"><span><small>All win</small>${pct(x.win, 0)}</span><span><small>Legs singly</small>${cents(x.mkt)}</span><span><small>Accept at most</small>${x.mx ? cents(x.mx) : "skip"}</span></span>
    </button>`,
      ).join("") +
      `<p class="small muted" style="margin:0">Confidence is the weakest leg's. Tap one to load it above. Parlays multiply risk: keep stakes small.</p>`
    : `<p class="muted small" style="margin:0">Fewer than two games with Kalshi prices in this window. Try a wider day or another sport.</p>`;
}
function suggest() {
  const x = parlayIdeas(1)[0];
  legs.clear();
  (x?.ls || []).forEach((p) => legs.add(p.ticker));
  note = x ? "" : "Fewer than two games with Kalshi prices in this window.";
  renderPicks();
  renderParlay();
}
$("#pIdeas").addEventListener("click", (e) => {
  const x = IDEAS[e.target.closest(".idea")?.dataset.i];
  if (!x) return;
  legs.clear();
  x.ls.forEach((p) => legs.add(p.ticker));
  renderPicks();
  renderParlay();
});
$("#pSuggest").addEventListener("click", suggest);
$("#parlay").addEventListener("click", (e) => {
  const t = e.target.dataset?.rm;
  if (t) {
    legs.delete(t);
    renderPicks();
    renderParlay();
  }
});

function renderParlay() {
  renderIdeas();
  const ls = [...legs].map(pick).filter(Boolean);
  if (ls.length !== legs.size)
    for (const t of [...legs]) if (!pick(t)) legs.delete(t); // a leg dropped off the board
  if (!ls.length) {
    $("#parlay").innerHTML =
      `<p class="muted small" style="margin:0">${esc(note) || "Tick 2 or 3 bets from different games, or tap a ready-made parlay below."}</p>`;
    return;
  }
  const win = ls.reduce((a, p) => a * p.fair, 1),
    mkt = ls.reduce((a, p) => a * p.price, 1),
    mx = maxPrice(win);
  const stake = U().max,
    payout = mx ? stake / (mx + fee(mx)) : null;
  $("#parlay").innerHTML = `${ls
    .map(
      (
        p,
      ) => `<div class="leg"><span>${esc(p.title)}</span><span class="mono">${pct(p.fair, 0)}
      <button class="link" data-rm="${esc(p.ticker)}" aria-label="Remove leg">×</button></span></div>`,
    )
    .join("")}
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
  for (const p of picks().filter((x) => x.slate))
    by[p.desk === "crypto" ? "Crypto" : p.league] =
      (by[p.desk === "crypto" ? "Crypto" : p.league] || 0) + p.stake;
  const rows = Object.entries(by).sort((a, b) => b[1] - a[1]),
    max = Math.max(1, ...rows.map((r) => r[1]));
  $("#exposure").innerHTML = rows.length
    ? rows
        .map(
          ([k, v]) => `<div class="bar"><span>${esc(k)}</span>
    <div class="track" role="img" aria-label="${esc(k)} ${usd(v, 0)}"><div class="fill" style="width:${(v / max) * 100}%"></div></div>
    <span class="v">${usd(v, 0)}</span></div>`,
        )
        .join("")
    : `<p class="muted small" style="margin:0">No capital at work.</p>`;
}

function spark(points) {
  if (!points?.length) return "";
  const ys = points.map((p) => p[1]),
    lo = Math.min(...ys),
    hi = Math.max(...ys),
    n = ys.length;
  const d = ys
    .map(
      (y, i) =>
        `${i ? "L" : "M"}${((i / (n - 1)) * 300).toFixed(1)},${(40 - ((y - lo) / (hi - lo || 1)) * 36 + 2).toFixed(1)}`,
    )
    .join("");
  return `<svg viewBox="0 0 300 44" preserveAspectRatio="none" role="img" aria-label="One-year price, low ${usd(lo)} high ${usd(hi)}"><path d="${d}"/></svg>`;
}

function renderCrypto() {
  const c = S.crypto || {};
  const keys = Object.keys(c);
  $("#crypto").innerHTML = keys.length
    ? keys
        .map((k) => {
          const x = c[k],
            trend =
              x.sma50 && x.sma200
                ? x.sma50 > x.sma200
                  ? "Uptrend"
                  : "Downtrend"
                : "–";
          const best = (x.strategies || [])
            .filter(
              (s) => s.id !== "buy_hold" && s.out_of_sample?.sharpe != null,
            )
            .sort((a, b) => b.out_of_sample.sharpe - a.out_of_sample.sharpe)[0];
          return `<div class="coin"><div class="row"><b>${esc(k.split("-")[0])}</b><span class="px">${usd(x.spot, 0)}</span></div>
      ${spark((x.chart || []).slice(-365))}
      <div class="stats">
        <div><span>Trend</span><b class="${trend === "Uptrend" ? "pos" : "neg"}">${trend}</b></div>
        <div><span>Vol (ann.)</span><b>${pct(x.vol_annual, 0)}</b></div>
        <div><span>RSI 14</span><b>${x.rsi14?.toFixed?.(0) ?? "–"}</b></div>
      </div>
      ${
        best
          ? `<div class="stats lab">
        <div><span>Daily-close signal</span><b class="${best.position > 0 ? "pos" : ""}">${best.position > 0 ? `Hold ${pct(best.position, 0)}` : "Stay in cash"}</b></div>
        <div><span>Next rebalance</span><b>${nextClose()}</b></div>
        <div><span>Holding period</span><b>${best.avg_hold_days ? `~${best.avg_hold_days} days` : "until it flips"}</b></div></div>
        <p class="small muted" style="margin:8px 0 0">${esc(best.name)}: Sharpe ${best.out_of_sample.sharpe.toFixed(2)} on unseen data. The rule only looks at the daily close (7 PM Eastern) and holds until its signal flips.</p>`
          : ""
      }
    </div>`;
        })
        .join("")
    : `<p class="muted small" style="padding:0 16px 14px;margin:0">Crypto data unavailable this run.</p>`;
}

const learnAgeH = () =>
  S?.learn?.last_ts ? (Date.now() / 1e3 - S.learn.last_ts) / 3600 : null;
function learnWarn() {
  const h = learnAgeH();
  return h == null
    ? "The learner has not finished a run yet. The first one runs after 4 AM Central."
    : h > 36
      ? `The learner last ran ${Math.round(h)} hours ago. It should run every night, so something is stuck.`
      : "";
}
function renderHealth() {
  const log = S.learn?.log || [],
    last = {};
  for (const r of log) last[r.league] = r;
  const rows = Object.values(last),
    warn = learnWarn();
  $("#learnDot").className = "dot " + (warn ? "bad" : "ok");
  $("#health").innerHTML =
    `<div class="health">${warn ? `<p class="warnbox small">${esc(warn)}</p>` : ""}${
      rows.length
        ? rows
            .map(
              (r) => `<div class="row">
      <span><i class="dot ${r.promoted ? "ok" : ""}"></i>${esc(String(r.league).toUpperCase())}</span>
      <span class="muted small">${r.promoted ? "New model promoted" : esc(r.reason || "Champion kept")}</span></div>`,
            )
            .join("")
        : `<span class="muted small">Nightly learning runs after 4 AM Central. First results appear tomorrow.</span>`
    }
    <div class="row small muted"><span>Ratings fitted on</span><span class="mono">${
      Object.entries(S.ratings_n || {})
        .map(([k, v]) => `${esc(k)} ${v}`)
        .join(" · ") || "–"
    }</span></div></div>`;
}

function renderSlate() {
  const gs = (S.games || []).filter((g) => g.state === "pre").slice(0, 60);
  const f1 = (v) => (v == null ? "–" : (+v).toFixed(1));
  $("#slate tbody").innerHTML = gs.length
    ? gs
        .map(
          (g) => `<tr><td>${esc(g.name)}</td><td>${esc(g.league)}</td>
    <td class="r">${startsIn(g.start)}</td><td class="r">${f1(g.model?.blend_margin)}</td><td class="r">${f1(g.book?.margin)}</td>
    <td class="r">${f1(g.model?.blend_total)}</td><td class="r">${f1(g.book?.total)}</td>
    <td class="muted small">${esc([...(g.model?.notes || [])].slice(0, 2).join("; "))}</td></tr>`,
        )
        .join("")
    : `<tr><td colspan="9" class="muted">No upcoming games with Kalshi markets.</td></tr>`;
}

function renderTrack() {
  const t = S.track?.total || {},
    b = S.track?.buckets || [];
  const head = `<div class="trackhead">
    <div><span>Graded</span><b>${t.graded ?? 0}</b></div>
    <div><span>Hit rate</span><b>${t.graded ? pct(t.wins / t.graded, 1) : "–"}</b></div>
    <div><span>ROI</span><b class="${(trackRoi() ?? 0) >= 0 ? "pos" : "neg"}">${pct(trackRoi(), 1, true)}</b></div>
    <div><span>Pending</span><b>${t.pending ?? 0}</b></div></div>`;
  const table = b.length
    ? `<div class="tablewrap"><table><thead><tr><th>League</th><th>Market</th><th>Edge bucket</th>
    <th class="r">Bets</th><th class="r">Hit</th><th class="r">Avg fair</th><th class="r">Avg price</th><th class="r">ROI</th><th class="r">CLV</th></tr></thead><tbody>
    ${b
      .map(
        (
          r,
        ) => `<tr><td>${esc(r.league)}</td><td>${esc(r.kind)}</td><td>${esc(r.bucket)}</td><td class="r">${r.n}</td>
      <td class="r">${pct(r.hit, 1)}</td><td class="r">${cents(r.avg_fair)}</td><td class="r">${cents(r.avg_price)}</td>
      <td class="r ${(r.roi ?? 0) >= 0 ? "pos" : "neg"}">${pct(r.roi, 1, true)}</td><td class="r">${r.clv == null ? "–" : pct(r.clv, 1, true)}</td></tr>`,
      )
      .join("")}
    </tbody></table></div>`
    : `<p class="empty">No graded picks yet. Results fill in as Kalshi settles each market.</p>`;
  $("#track").innerHTML = head + table;
}

// ---------- every game ----------
// Best side of each market for every upcoming game, picks or not. Read-only: leans and no-edge rows
// never enter plan(), the budget or the Autotracker.
function gameMatches(g) {
  if (g.state !== "pre" || !inWindow(g)) return false;
  if (F.league && g.league !== F.league) return false;
  if (F.q) {
    const hay = [g.name, g.home?.name, g.home?.abbr, g.away?.name, g.away?.abbr]
      .join(" ")
      .toLowerCase();
    if (
      !F.q
        .toLowerCase()
        .split(" ")
        .filter(Boolean)
        .every((w) => hay.includes(w))
    )
      return false;
  }
  return true;
}
function betLabel(g, c) {
  const t = g[c.team]?.abbr || c.team;
  if (c.kind === "winner") return `${t} to win`;
  if (c.kind === "spread") return `${t} wins by ${c.line}+`;
  if (c.kind === "team_total") return `${t} over ${c.line} pts`;
  return `Total over ${c.line}`;
}
function boardRow(g, kind, onSlate) {
  const cs = (g.contracts || []).filter((c) => c.kind === kind && c.best);
  if (!cs.length) return null;
  const picked = cs.filter((c) => onSlate.has(c.ticker));
  const main =
    kind === "winner"
      ? cs
      : cs.filter((c) => c.yes_ask >= 0.3 && c.yes_ask <= 0.7);
  const pool = picked.length ? picked : main.length ? main : cs;
  const c = pool.reduce((a, b) => (b.best.edge > a.best.edge ? b : a));
  const b = c.best,
    cost = b.price + fee(b.price);
  const status = onSlate.has(c.ticker) ? "pick" : b.edge > 0 ? "lean" : "pass";
  return { c, b, status, per10: cost > 0 ? (10 * b.edge) / cost : 0 };
}
// Verdict next to the numbers: "BET: side at price" when it passes every gate, otherwise "No bet" + why.
function verdict(r) {
  if (r.status === "pick")
    return `<span class="st pick">BET: ${r.b.side.toUpperCase()} at ${cents(r.b.price)}</span>`;
  const book = r.c.p_book == null ? null : r.b.side === "yes" ? r.c.p_book : 1 - r.c.p_book;
  const why =
    book != null && Math.abs(r.b.fair - book) > 0.08
      ? "model and Vegas disagree"
      : r.b.edge > 0
        ? "edge too small"
        : "no edge after fees";
  return `<span class="st ${r.status}">No bet</span><br><small class="muted">${why}</small>`;
}
// Our call on the game itself: projected score from the blended model + book line.
function prediction(g) {
  const m = g.model?.blend_margin, t = g.model?.blend_total;
  if (m == null || t == null) return "";
  const h = (t + m) / 2, a = (t - m) / 2, w = m >= 0 ? g.home : g.away;
  const win = (g.contracts || []).find((c) => c.kind === "winner" && c.team === (m >= 0 ? "home" : "away"));
  const p = win?.p_fair != null ? ` (${pct(win.p_fair, 0)})` : "";
  return `Our call: <b>${esc(w?.abbr || w?.name || "")}</b>${p}, ${esc(g.away?.abbr || "")} ${Math.round(a)} – ${esc(g.home?.abbr || "")} ${Math.round(h)}`;
}
function renderBoard() {
  if (!S) return;
  const onSlate = new Set(
    plan()
      .filter((p) => p.slate)
      .map((p) => p.ticker),
  );
  const gs = (S.games || [])
    .filter(gameMatches)
    .sort((a, b) => ((a.start || "") < (b.start || "") ? -1 : 1));
  $("#boardCount").textContent = gs.length ? `(${gs.length})` : "";
  const sideP = (p, side) => (p == null ? null : side === "yes" ? p : 1 - p);
  const rows = gs.map((g) =>
    ["winner", "spread", "total", "team_total"]
      .map((k) => boardRow(g, k, onSlate))
      .filter(Boolean)
      .map((r, i) => {
        const click =
          r.status === "pick"
            ? ` data-t="${esc(r.c.ticker)}" tabindex="0"`
            : "";
        const head = i
          ? ""
          : `<b>${esc(g.name)}</b><br><small class="muted">${esc(g.league)} · ${startsIn(g.start)}</small><br><small>${prediction(g)}</small>`;
        const tt =
          r.c.kind === "team_total"
            ? ` <small class="muted" title="Team totals are watch-only until the track record shows they profit">watch only</small>`
            : "";
        return `<tr class="${i ? "" : "gstart "}${r.status}"${click}>
      <td>${head}</td>
      <td>Buy <b>${r.b.side.toUpperCase()}</b> on ${esc(betLabel(g, r.c))}${tt}</td>
      <td class="r">${pct(r.b.fair)}</td><td class="r">${pct(sideP(r.c.p_book, r.b.side))}</td>
      <td class="r">${cents(r.c.yes_bid)} / ${cents(r.c.yes_ask)}</td>
      <td class="r">${cents(r.b.fair)}</td>
      <td class="r ${r.b.edge > 0 ? "pos" : "muted"}">${pct(r.b.edge)}</td>
      <td class="r ${r.per10 > 0 ? "pos" : "muted"}">${r.per10 >= 0 ? "+" : "-"}$${Math.abs(r.per10).toFixed(2)}</td>
      <td>${verdict(r)}</td></tr>`;
      })
      .join(""),
  );
  $("#board tbody").innerHTML =
    rows.join("") ||
    `<tr><td colspan="9" class="muted">No upcoming games with Kalshi markets in this window.</td></tr>`;
}
$("#board").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-t]");
  if (tr) openPick(tr.dataset.t);
});
// ---------- your slate ----------
const UIN = {
  bankroll: "#uBank",
  budget: "#uBudget",
  max: "#uMax",
  open: "#uOpen",
};
function renderSettings() {
  const u = U();
  for (const [k, sel] of Object.entries(UIN))
    if (document.activeElement !== $(sel)) $(sel).value = u[k];
}
$("#settings").addEventListener("input", () => {
  const u = {};
  for (const [k, sel] of Object.entries(UIN))
    u[k] = $(sel).value === "" ? null : Math.max(0, +$(sel).value);
  saveU(u);
  $("#bankroll").textContent = usd(U().bankroll);
  update();
  renderParlay();
});
$("#uReset").addEventListener("click", () => {
  try {
    localStorage.removeItem(UKEY);
  } catch {}
  renderSettings();
  update();
});

function renderPlan() {
  if (!S) return;
  const u = U(),
    all = plan(),
    on = all.filter((p) => p.slate),
    used = on.reduce((a, p) => a + p.stake, 0);
  const ev = on.reduce((a, p) => a + p.exp_profit, 0),
    room = Math.max(0, u.budget - u.open);
  $("#slatePlan").innerHTML = `<div class="trackhead">
      <div><span>Bets</span><b>${on.length}</b></div>
      <div><span>Total stake</span><b>${usd(used, 2)}</b><small class="muted">of ${usd(room, 0)} free budget</small></div>
      <div><span>Expected profit</span><b class="${ev > 0 ? "pos" : ""}">${usd(ev, 2)}</b></div>
      <div><span>Watch only</span><b>${all.length - on.length}</b></div></div>
    ${
      on.length
        ? `<div class="tablewrap"><table><thead><tr><th>Bet</th><th class="r">Price</th><th class="r">Win chance</th>
      <th class="r">Contracts</th><th class="r">Stake</th><th class="r">Starts</th></tr></thead><tbody>
      ${on
        .map(
          (
            p,
          ) => `<tr data-t="${esc(p.ticker)}" tabindex="0"><td><span class="tag">${esc(p.desk === "crypto" ? "CRYPTO" : p.league)}</span>${esc(p.desk === "crypto" ? cryptoAction(p) : p.title)}</td>
        <td class="r">${cents(p.price)}</td><td class="r">${pct(p.fair, 0)}</td><td class="r">${p.count}</td><td class="r">${usd(p.stake, 2)}</td>
        <td class="r">${startsIn(p.start || p.close)}</td></tr>`,
        )
        .join("")}</tbody></table></div>`
        : `<p class="empty">${room < 1 ? "Your budget is fully used by open bets." : "No bet clears the bar right now."}</p>`
    }
    <p class="small muted pad">One bet per game, at most ${usd(u.max, 2)} each and ${usd(u.budget, 0)} riding at once. Likely winners (55%+) fill first. Everything else stays watch-only. Your numbers are saved in this browser only.</p>`;
}
$("#slatePlan").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-t]");
  if (tr) openPick(tr.dataset.t);
});

// ---------- crypto ----------
const ET = "America/New_York";
const etTime = (iso) =>
  new Date(iso).toLocaleString("en-US", {
    timeZone: ET,
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  }) + " ET";
const coinOf = (p) => (p.product || p.title || "").split(/[- ]/)[0];
const px = (v) => (v == null ? "?" : usd(v, v < 100 ? 2 : 0));
function cryptoAction(p) {
  const c = coinOf(p),
    st = (p.strike_type || "").toLowerCase(),
    when = p.close ? etTime(p.close) : "close";
  const yes = st.startsWith("greater")
    ? `${c} is above ${px(p.floor)}`
    : st.startsWith("less")
      ? `${c} is below ${px(p.cap)}`
      : st === "between"
        ? `${c} is between ${px(p.floor)} and ${px(p.cap)}`
        : p.sub || p.title;
  const no = st.startsWith("greater")
    ? `${c} is at or below ${px(p.floor)}`
    : st.startsWith("less")
      ? `${c} is at or above ${px(p.cap)}`
      : st === "between"
        ? `${c} is outside ${px(p.floor)} to ${px(p.cap)}`
        : `not (${p.sub || p.title})`;
  return `Buy ${p.side.toUpperCase()} at ${cents(p.price)}: wins if ${p.side === "yes" ? yes : no} at ${when}`;
}
function strikeGap(p) {
  if (!p.spot) return "–";
  const st = (p.strike_type || "").toLowerCase(),
    k = st.startsWith("less")
      ? p.cap
      : st === "between"
        ? (p.floor + p.cap) / 2
        : p.floor;
  return k == null
    ? "–"
    : `${px(p.spot)} → ${px(k)} <small class="muted">(${pct((k - p.spot) / p.spot, 1, true)})</small>`;
}
function countdown(iso) {
  const m = (Date.parse(iso) - Date.now()) / 60e3;
  if (m <= 0) return "settling";
  return m < 60
    ? `${Math.ceil(m)}m`
    : m < 48 * 60
      ? `${Math.floor(m / 60)}h ${Math.round(m % 60)}m`
      : `${Math.round(m / 1440)}d`;
}
let CW = "today";
function inCw(p) {
  const t = Date.parse(p.close),
    now = Date.now();
  if (!(t > now)) return false;
  const d = (x) => new Date(x).toLocaleDateString("en-CA", { timeZone: ET });
  return CW === "hour"
    ? t - now <= 36e5
    : CW === "today"
      ? d(t) === d(now)
      : CW === "tomorrow"
        ? d(t) === d(now + 864e5)
        : t - now <= 7 * 864e5;
}
function renderCryptoBets() {
  if (!S) return;
  for (const b of document.querySelectorAll("#cWhen button"))
    b.setAttribute("aria-selected", b.dataset.c === CW);
  const ps = plan()
    .filter((p) => p.desk === "crypto" && p.close && inCw(p))
    .sort((a, b) => Date.parse(a.close) - Date.parse(b.close));
  $("#cTable tbody").innerHTML = ps.length
    ? ps
        .map(
          (
            p,
          ) => `<tr data-t="${esc(p.ticker)}" tabindex="0" class="${p.slate ? "" : "watch"}">
      <td><b>${esc(cryptoAction(p))}</b><small class="muted"> ${esc(p.ticker)}</small></td><td class="r">${strikeGap(p)}</td>
      <td class="r">${pct(p.fair, 0)}</td><td class="r ${p.edge > 0 ? "pos" : "neg"}">${pct(p.edge, 1, true)}</td>
      <td class="r">${p.slate ? usd(p.stake, 2) : '<span class="muted">watch</span>'}</td>
      <td class="r">${etTime(p.close)}<small class="muted"> · ${countdown(p.close)}</small></td></tr>`,
        )
        .join("")
    : `<tr><td colspan="6" class="muted">No crypto bet with an edge settles in this window.</td></tr>`;
}
$("#cWhen").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-c]");
  if (b) {
    CW = b.dataset.c;
    renderCryptoBets();
  }
});
$("#cTable").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-t]");
  if (tr) openPick(tr.dataset.t);
});
function nextClose() {
  // Coinbase daily candles close at 00:00 UTC
  const n = new Date();
  n.setUTCHours(24, 0, 0, 0);
  return (
    n.toLocaleString("en-US", {
      timeZone: ET,
      weekday: "short",
      hour: "numeric",
    }) + " ET"
  );
}

// ---------- autotracker ----------
function curveSvg(pts, base) {
  if (!pts || pts.length < 2) return "";
  pts = [...pts].sort((a, b) => a[0] - b[0]);
  const xs = pts.map((p) => p[0]),
    ys = pts.map((p) => p[1]),
    x0 = Math.min(...xs),
    x1 = Math.max(...xs);
  const lo = Math.min(base, ...ys),
    hi = Math.max(base, ...ys),
    X = (x) => ((x - x0) / (x1 - x0 || 1)) * 600,
    Y = (y) => 116 - ((y - lo) / (hi - lo || 1)) * 108;
  const d = pts
    .map(
      (p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`,
    )
    .join("");
  return `<svg class="curve" viewBox="0 0 600 120" preserveAspectRatio="none" role="img" aria-label="Paper equity from ${usd(ys[0])} to ${usd(ys[ys.length - 1], 2)}">
    <line x1="0" x2="600" y1="${Y(base).toFixed(1)}" y2="${Y(base).toFixed(1)}" class="base"/><path d="${d}"/></svg>`;
}
const LAB = {
  league: "League",
  market: "Market",
  side: "Favourite or underdog",
  price: "Price paid",
  grade: "Grade",
};
function renderAuto() {
  const a = S.autotrack;
  if (!a) {
    $("#auto").innerHTML =
      `<p class="empty">The autotracker starts with the next refresh.</p>`;
    return;
  }
  const t = a.total || {},
    since = new Date(a.since * 1e3).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  const tbl = (key) => {
    const r = a.by?.[key] || [];
    return r.length
      ? `<div class="tablewrap"><table><thead><tr><th>${LAB[key]}</th><th class="r">W-L</th>
      <th class="r">Win rate</th><th class="r">Staked</th><th class="r">P&amp;L</th><th class="r">ROI</th><th class="r">Avg CLV</th></tr></thead><tbody>
      ${r
        .map(
          (
            x,
          ) => `<tr><td>${esc(x.key)}</td><td class="r">${x.w}-${x.l}</td><td class="r">${pct(x.win_rate, 0)}</td><td class="r">${usd(x.staked, 2)}</td>
      <td class="r ${x.pnl >= 0 ? "pos" : "neg"}">${usd(x.pnl, 2)}</td><td class="r ${(x.roi ?? 0) >= 0 ? "pos" : "neg"}">${pct(x.roi, 1, true)}</td>
      <td class="r">${x.avg_clv == null ? "–" : (x.avg_clv * 100).toFixed(1) + "¢"}</td></tr>`,
        )
        .join("")}</tbody></table></div>`
      : "";
  };
  $("#auto").innerHTML =
    `<p class="small muted pad">Takes every bet on the slate automatically with a separate ${usd(a.bankroll)} paper bankroll, under the same ${usd(a.budget)} budget and ${usd(a.max_bet, 2)} max bet, at the price shown plus Kalshi's fee. Graded when Kalshi settles. Tracking since ${since} · model ${esc((a.versions || []).join(", ") || S.version || "–")}.</p>
    <div class="trackhead">
      <div><span>Paper equity</span><b class="${a.equity >= a.bankroll ? "pos" : "neg"}">${usd(a.equity, 2)}</b></div>
      <div><span>W-L</span><b>${t.n ? `${t.w}-${t.l}` : "–"}</b></div>
      <div><span>Win rate</span><b>${pct(t.win_rate, 0)}</b></div>
      <div><span>P&amp;L</span><b class="${(t.pnl ?? 0) >= 0 ? "pos" : "neg"}">${usd(t.pnl, 2)}</b></div>
      <div><span>ROI</span><b>${pct(t.roi, 1, true)}</b></div>
      <div><span>Avg CLV</span><b title="Closing price minus price paid. Positive means we beat the market.">${t.avg_clv == null ? "–" : (t.avg_clv * 100).toFixed(1) + "¢"}</b></div>
      <div><span>Open risk</span><b>${usd(a.open_risk, 2)}</b></div></div>
    ${curveSvg(a.curve, a.bankroll) || `<p class="empty">The equity curve starts once the first bet settles.</p>`}
    <h3 class="sub">Open positions (${(a.open || []).length})</h3>
    ${
      (a.open || []).length
        ? `<div class="tablewrap"><table><thead><tr><th>Bet</th><th class="r">Price</th><th class="r">Contracts</th><th class="r">Cost</th><th class="r">Settles in</th></tr></thead><tbody>
      ${a.open
        .map(
          (
            b,
          ) => `<tr><td><span class="tag">${esc(b.league)}</span>${esc(b.title)}</td><td class="r">${cents(b.price)}</td><td class="r">${b.count}</td>
      <td class="r">${usd(b.cost, 2)}</td><td class="r">${countdown(b.start || b.close)}</td></tr>`,
        )
        .join("")}</tbody></table></div>`
        : `<p class="empty">Nothing open.</p>`
    }
    ${
      t.n
        ? `<h3 class="sub">Breakdowns</h3>${Object.keys(LAB).map(tbl).join("")}
      <h3 class="sub">Recent results</h3><div class="tablewrap"><table><thead><tr><th>Bet</th><th class="c">Result</th><th class="r">P&amp;L</th><th class="r">CLV</th></tr></thead><tbody>
      ${(a.recent || [])
        .map(
          (
            b,
          ) => `<tr><td><span class="tag">${esc(b.league)}</span>${esc(b.title)}</td><td class="c ${b.result === "W" ? "pos" : "neg"}">${b.result}</td>
      <td class="r ${b.pnl >= 0 ? "pos" : "neg"}">${usd(b.pnl, 2)}</td><td class="r">${b.clv == null ? "–" : (b.clv * 100).toFixed(1) + "¢"}</td></tr>`,
        )
        .join("")}</tbody></table></div>`
        : `<p class="empty">No bets settled yet. Breakdowns by league, market, favourite vs underdog, price and grade appear as results come in.</p>`
    }`;
}

// ---------- learning ----------
function calChart(rows) {
  if (!rows?.length)
    return `<p class="empty">The calibration chart fills in as picks settle: each dot is a price band, and dots on the diagonal mean our win chances are honest.</p>`;
  const P = (v) => 20 + v * 260,
    maxN = Math.max(...rows.map((r) => r.n));
  return `<svg class="cal" viewBox="0 0 300 300" role="img" aria-label="Predicted versus actual win rate">
    <line x1="${P(0)}" y1="${300 - P(0)}" x2="${P(1)}" y2="${300 - P(1)}" class="diag"/>
    ${[0, 0.25, 0.5, 0.75, 1].map((v) => `<text x="${P(v)}" y="296" text-anchor="middle">${v * 100}%</text><text x="2" y="${304 - P(v)}">${v * 100}</text>`).join("")}
    ${rows.map((r) => `<circle cx="${P(r.predicted)}" cy="${300 - P(r.actual)}" r="${3 + 6 * Math.sqrt(r.n / maxN)}"><title>${r.band}%: predicted ${pct(r.predicted, 0)}, won ${pct(r.actual, 0)} of ${r.n}</title></circle>`).join("")}
    </svg><p class="small muted pad">Across: the win chance we gave. Up: how often those picks actually won.</p>`;
}
function renderLearn() {
  const L = S.learn || {},
    c = L.calibration || {},
    warn = learnWarn(),
    last = {};
  for (const r of L.log || []) last[r.league] = r;
  const ll = (v) => (v == null ? "–" : (+v).toFixed(4));
  $("#learn").innerHTML = `${warn ? `<p class="warnbox">${esc(warn)}</p>` : ""}
    <div class="trackhead">
      <div><span>Last run</span><b>${L.last_ts ? new Date(L.last_ts * 1e3).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" }) : "not yet"}</b></div>
      <div><span>Model vs market weight</span><b>${pct(L.w_market, 0)}</b><small class="muted">rest comes from the Kalshi price</small></div>
      <div><span>Graded picks used</span><b>${c.n ?? 0}</b></div>
      <div><span>Weight change</span><b>${c.promoted ? "Promoted" : "Held"}</b><small class="muted">${esc(c.reason || "")}</small></div></div>
    <h3 class="sub">By league</h3>
    ${
      Object.keys(last).length
        ? `<div class="tablewrap"><table><thead><tr><th>League</th><th class="r">Games tested</th><th class="r">Champion log loss</th>
      <th class="r">Challenger log loss</th><th>Result</th></tr></thead><tbody>${Object.values(
        last,
      )
        .map(
          (r) => `<tr><td>${esc(String(r.league).toUpperCase())}</td>
      <td class="r">${r.holdout_n ?? "–"}</td><td class="r">${ll(r.champion_logloss)}</td><td class="r">${ll(r.challenger_logloss)}</td>
      <td>${r.promoted ? '<b class="pos">Promoted</b>' : esc(r.reason || "Champion kept")}</td></tr>`,
        )
        .join("")}</tbody></table></div>`
        : `<p class="empty">No nightly run logged yet.</p>`
    }
    <h3 class="sub">Calibration</h3>${calChart(L.deciles)}
    <p class="small muted pad">Every night the model is refit on games it has not seen and only replaces the current one if it predicts them better (lower log loss). The same check decides how much to trust our numbers versus the Kalshi price.</p>`;
}

// ---------- tabs ----------
function showTab(t, push = false) {
  TAB = VIEWS.includes(t) ? t : "board";
  for (const a of document.querySelectorAll("#tabs a"))
    a.toggleAttribute("aria-current", a.dataset.tab === TAB);
  for (const d of document.querySelectorAll("[data-pane]"))
    d.hidden = d.dataset.pane !== TAB;
  saveUrl(push);
}
$("#tabs").addEventListener("click", (e) => {
  const a = e.target.closest("a[data-tab]");
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey) return; // let new-tab clicks through
  e.preventDefault();
  showTab(a.dataset.tab, true);
  scrollTo(0, 0);
});
addEventListener("popstate", () => {
  loadUrl();
  showTab(TAB);
  if (S) update();
});

// ---------- theme ----------
(function theme() {
  let saved = null;
  try {
    saved = localStorage.getItem("kil-theme");
  } catch {}
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme").onclick = () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try {
      localStorage.setItem("kil-theme", document.documentElement.dataset.theme);
    } catch {}
  };
})();

loadUrl();
showTab(TAB);
pullState();
setInterval(pullState, STATE_EVERY);
setInterval(() => {
  setFeed();
  if (S) {
    renderPicks();
    renderCryptoBets();
  }
}, 30e3); // keep countdowns fresh
// keep the sticky filter bar right under the header, whatever height the header wraps to
new ResizeObserver(([e]) =>
  document.documentElement.style.setProperty("--hdr", e.target.offsetHeight + "px"),
).observe($(".top"));
