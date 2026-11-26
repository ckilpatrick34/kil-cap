// Kil Capital v3 dashboard: games, crypto, paper book, track record.  Paper only; no key ever reaches the page.
const TOKEN = window.KIL_TOKEN;
const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const cents = (p) => (p == null ? "—" : Math.round(p * 100) + "¢");
const pct = (x, d = 0) => (x == null ? "—" : (x * 100).toFixed(d) + "%");
const usd = (x) =>
  x == null
    ? "—"
    : (Number(x) < 0 ? "-$" : "$") + Math.abs(Number(x)).toFixed(2);
const sgn = (x) => (x == null ? "" : Number(x) >= 0 ? "pos" : "neg");
const when = (iso) =>
  iso
    ? new Date(iso).toLocaleString([], {
        weekday: "short",
        hour: "numeric",
        minute: "2-digit",
      })
    : "";
const ago = (iso) => {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso)) / 1000;
  return s < 90 ? "just now" : Math.round(s / 60) + " min ago";
};

async function api(path, body) {
  const o = body
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Kil-Token": TOKEN },
        body: JSON.stringify(body),
      }
    : {};
  const r = await fetch(path, o);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || j.error || r.statusText);
  return j;
}
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("on");
  setTimeout(() => t.classList.remove("on"), 3000);
}
function table(head, rows, empty) {
  if (!rows.length) return `<div class="empty">${empty}</div>`;
  return `<table><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
}

// ---------- state ----------
const S = {
  slate: null,
  crypto: null,
  paper: null,
  league: "All",
  coin: "BTC-USD",
};

// ---------- tabs ----------
$("tabs").onclick = (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  document
    .querySelectorAll("#tabs button")
    .forEach((x) => x.classList.toggle("on", x === b));
  document
    .querySelectorAll(".tab")
    .forEach((t) => t.classList.toggle("on", t.id === "tab-" + b.dataset.tab));
};

// ---------- buy (paper) ----------
async function buy(ticker, side, count, sid, fair) {
  try {
    await api("/api/paper/buy", {
      ticker,
      side,
      count: Math.max(1, count | 0),
      strategy_id: sid,
      fair: fair == null ? null : String(fair),
    });
    toast(`Paper bought ${count} ${side.toUpperCase()}`);
    loadPaper();
  } catch (e) {
    toast("Not bought: " + e.message);
  }
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-buy]");
  if (!b) return;
  e.stopPropagation();
  const [t, side, n, sid, fair] = b.dataset.buy.split("|");
  buy(t, side, +n, sid, fair === "" ? null : +fair);
});
const buyBtn = (s) =>
  `<button class="primary" data-buy="${esc(s.ticker)}|${s.side}|${s.count || 1}|${s.strategy_id}|${s.fair ?? ""}">Paper buy ${s.count || 1}</button>`;

// ---------- games ----------
function renderGames() {
  const st = S.slate;
  if (!st) return;
  const leagues = ["All", ...new Set(st.games.map((g) => g.league))];
  $("lg-filter").innerHTML = leagues
    .map(
      (l) =>
        `<button class="${l === S.league ? "on" : ""}" data-lg="${esc(l)}">${esc(l)}</button>`,
    )
    .join("");
  const keep = (x) => S.league === "All" || x.league === S.league;
  const picks = st.signals.filter(keep).map(
    (s) => `<tr>
      <td><span class="grade ${s.confidence}">${s.confidence}</span></td>
      <td><b>${esc(s.title)}</b><div class="muted small">${esc(s.league)} · ${when(s.start)}</div></td>
      <td class="num">Buy <span class="side ${s.side}">${s.side.toUpperCase()}</span> at ${cents(s.price)}</td>
      <td class="num">Fair ${cents(s.fair)}</td>
      <td class="num pos"><b>+${(s.edge * 100).toFixed(1)}¢</b></td>
      <td class="num hide-sm">${s.roi != null ? `${(s.roi * 100).toFixed(0)}%` : "—"}</td>
      <td class="num hide-sm">${usd(s.stake)}</td>
      <td class="num pos">${s.exp_profit != null ? usd(s.exp_profit) : "—"}</td><td>${buyBtn(s)}</td></tr>`,
  );
  $("picks").innerHTML = table(
    ["Grade", "Pick", "Action", "Our price", "Edge", "ROI", "Kelly size", "Exp. profit", ""],
    picks,
    st.updated
      ? "No game clears every gate right now. That's normal: most lines are efficient. Check back closer to tip-off."
      : "Building ratings from past games (first load takes a minute or two)…",
  );
  const games = st.games.filter(keep).map((g) => {
    const b = g.book || {},
      m = g.model || {};
    const line = (v) => (v == null ? "—" : (v > 0 ? "+" : "") + v.toFixed(1));
    return `<tr class="click game-row" data-gid="${esc(g.id)}"><td>${esc(g.league)}<br>${when(g.start)}</td>
      <td class="teams"><b>${esc(g.away?.abbr)}</b><span class="vs">@</span><b>${esc(g.home?.abbr)}</b><div class="muted small">${esc(g.detail || "")}</div></td>
      <td class="num">Home by ${line(m.blend_margin)}<div class="muted small">Model ${line(m.margin)} · Book ${line(b.margin)}</div></td>
      <td class="num">${m.blend_total == null ? "—" : m.blend_total.toFixed(1)}<div class="muted small">Book ${b.total ?? "—"}</div></td>
      <td>${g.n_trades ? `<span class="tag keep">${g.n_trades} pick${g.n_trades > 1 ? "s" : ""}</span>` : `<span class="tag">${g.n_contracts} markets</span>`}</td></tr>`;
  });
  $("games").innerHTML = table(
    ["League", "Game", "Our margin", "Our total", ""],
    games,
    "No games with Kalshi markets in the next two days.",
  );
}
$("lg-filter").onclick = (e) => {
  const b = e.target.closest("button");
  if (b) {
    S.league = b.dataset.lg;
    renderGames();
  }
};
$("games").onclick = async (e) => {
  const r = e.target.closest("tr[data-gid]");
  if (!r) return;
  try {
    openGame(await api("/api/slate/game/" + encodeURIComponent(r.dataset.gid)));
  } catch (err) {
    toast(err.message);
  }
};
function openGame(g) {
  const m = g.model || {},
    notes = [...(m.notes || [])];
  if (m.weather)
    notes.push(
      `Weather: ${m.weather.temp_f ?? "?"}°F, wind ${m.weather.wind_mph ?? "?"} mph`,
    );
  const rows = g.contracts.map((c) => {
    const b = c.best || {};
    const label =
      c.kind === "winner"
        ? `${g[c.team]?.abbr} to win`
        : c.kind === "spread"
          ? `${g[c.team]?.abbr} by ${c.line}+`
          : `Over ${c.line}`;
    return `<tr><td>${esc(label)}</td><td class="num">${cents(c.yes_bid)} / ${cents(c.yes_ask)}</td>
      <td class="num">${cents(c.p_model)}</td><td class="num">${cents(c.p_book)}</td><td class="num"><b>${cents(c.p_fair)}</b></td>
      <td class="num ${b.edge > 0 ? "pos" : "muted"}">${b.side ? `${b.side.toUpperCase()} ${(b.edge * 100).toFixed(1)}¢` : "—"}</td>
      <td>${c.tradeable ? buyBtn({ ticker: c.ticker, side: b.side, count: c.count, strategy_id: "game_model", fair: b.fair }) : ""}</td></tr>`;
  });
  const inj = Object.entries(m.injuries || {}).map(([t, ns]) => `<span class="tag">${esc(t)} out: ${esc([].concat(ns).slice(0, 4).join(", "))}</span>`).join("");
  $("drawer-body").innerHTML =
    `<h3>${esc(g.name)}</h3><p class="muted">${esc(g.league)} · ${when(g.start)} · ${esc(g.venue || "")}</p>
    <div class="notes">${notes.map((n) => `<span class="tag">${esc(n)}</span>`).join("")}${inj}</div>
    <p class="muted small">Model uses ${m.games_played ?? "?"} games of results. Fair = our model blended with the de-vigged sportsbook line.</p>
    ${table(["Contract", "Kalshi bid / ask", "Model", "Book", "Fair", "Best side", ""], rows, "No Kalshi contracts.")}`;
  $("drawer").classList.add("on");
}
$("drawer-x").onclick = () => $("drawer").classList.remove("on");
$("drawer").onclick = (e) => {
  if (e.target.id === "drawer") $("drawer").classList.remove("on");
};

// ---------- crypto ----------
function spark(pts) {
  if (!pts || pts.length < 2) return "";
  const ys = pts.map((p) => p[1]),
    lo = Math.min(...ys),
    hi = Math.max(...ys),
    w = 600,
    h = 120;
  const d = pts
    .map(
      (p, i) =>
        `${i ? "L" : "M"}${((i / (pts.length - 1)) * w).toFixed(1)},${(h - ((p[1] - lo) / (hi - lo || 1)) * (h - 8) - 4).toFixed(1)}`,
    )
    .join("");
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path d="${d}"/></svg>`;
}
function renderCrypto() {
  const c = S.crypto;
  if (!c) return;
  const P = c.products || {};
  $("crypto-head").innerHTML =
    Object.entries(P)
      .map(([k, p]) => {
        const trend =
          p.sma200 && p.spot > p.sma200
            ? `<span class="tag keep">Above 200-day</span>`
            : `<span class="tag drop">Below 200-day</span>`;
        const rsiTag =
          p.rsi14 > 70 ? "overbought" : p.rsi14 < 30 ? "oversold" : "neutral";
        return `<div class="card"><div class="card-head"><div><h2>${k.split("-")[0]} $${Math.round(p.spot).toLocaleString()}</h2>
      <p class="muted">RSI ${p.rsi14?.toFixed(0)} (${rsiTag}) · volatility ${pct(p.vol_annual)} a year</p></div>${trend}</div>${spark(p.chart)}</div>`;
      })
      .join("") ||
    `<div class="card empty">${(c.errors || []).join("; ") || "Loading price history…"}</div>`;
  const picks = (c.signals || []).map(
    (
      s,
    ) => `<tr><td><span class="grade ${s.confidence}">${s.confidence}</span></td>
    <td><b>${esc(s.title)}</b></td><td class="num">Buy <span class="side ${s.side}">${s.side.toUpperCase()}</span> at ${cents(s.price)}</td>
    <td class="num">Fair ${cents(s.fair)}</td><td class="num pos"><b>+${(s.edge * 100).toFixed(1)}¢</b></td><td>${buyBtn(s)}</td></tr>`,
  );
  $("crypto-picks").innerHTML = table(
    ["Grade", "Contract", "Action", "Our price", "Edge", ""],
    picks,
    "No crypto contract clears the edge and price gates right now.",
  );
  $("coin-filter").innerHTML = Object.keys(P)
    .map(
      (k) =>
        `<button class="${k === S.coin ? "on" : ""}" data-coin="${k}">${k.split("-")[0]}</button>`,
    )
    .join("");
  const strat = ((P[S.coin] || {}).strategies || [])
    .slice()
    .sort(
      (a, b) =>
        (b.out_of_sample?.sharpe ?? -9) - (a.out_of_sample?.sharpe ?? -9),
    );
  const rows = strat.map((s) => {
    const o = s.out_of_sample || {},
      f = s.forward;
    return `<tr><td><b>${esc(s.name)}</b><div class="muted small">${esc(s.desc)}</div></td>
      <td><span class="tag ${s.verdict}">${esc(s.verdict || "—")}</span></td>
      <td class="num ${sgn(o.cagr)}">${pct(o.cagr)}</td><td class="num">${o.sharpe == null ? "—" : o.sharpe.toFixed(2)}</td>
      <td class="num neg">${pct(o.max_dd == null ? null : -o.max_dd)}</td><td class="num">${s.luck_p == null ? "—" : pct(s.luck_p)}</td>
      <td class="num">${s.position > 0 ? `<span class="pos">In ${pct(s.position)}</span>` : "Flat"}</td>
      <td class="num hide-sm ${sgn(f?.return)}">${f ? `${pct(f.return, 1)} in ${f.days}d` : "—"}</td></tr>`;
  });
  $("strategies").innerHTML = table(
    [
      "Strategy",
      "Verdict",
      "Yearly return",
      "Sharpe",
      "Worst drop",
      "Luck",
      "Now",
      "Since go-live",
    ],
    rows,
    "Backtests run once the price history loads.",
  );
}
$("coin-filter").onclick = (e) => {
  const b = e.target.closest("button");
  if (b) {
    S.coin = b.dataset.coin;
    renderCrypto();
  }
};

// ---------- paper book ----------
function renderPaper() {
  const p = S.paper;
  if (!p) return;
  $("k-equity").textContent = usd(p.equity);
  $("k-pnl").textContent = usd(p.total_pnl);
  $("k-pnl").className = sgn(p.total_pnl);
  $("k-clv").textContent =
    p.avg_clv == null
      ? "—"
      : (p.avg_clv >= 0 ? "+" : "") + (p.avg_clv * 100).toFixed(1) + "¢";
  const a = p.autopilot || {};
  $("auto-on").checked = !!a.enabled;
  $("auto-label").textContent = a.enabled ? "Autopilot on" : "Autopilot off";
  if (document.activeElement?.tagName !== "INPUT") {
    $("auto-edge").value = Math.round(+a.min_edge * 100);
    $("auto-trade").value = +a.max_trade_usd;
    $("auto-total").value = +a.max_total_usd;
  }
  $("book-kpis").innerHTML = [
    ["Cash", usd(p.cash)],
    ["At risk", usd(p.at_risk)],
    ["Realized P&L", usd(p.realized)],
    ["Closed trades", `${p.closed_trades} (${p.wins} won)`],
  ]
    .map(([k, v]) => `<div class="stat"><span>${k}</span><b>${v}</b></div>`)
    .join("");
  const rows = (p.positions || []).map(
    (
      x,
    ) => `<tr><td><b>${esc(x.title || x.ticker)}</b><div class="muted small">${esc(x.strategy_id || "")}</div></td>
    <td><span class="side ${x.side}">${x.side.toUpperCase()}</span> × ${x.count}</td><td class="num">${cents(+x.avg_price)}</td>
    <td class="num">${x.bid == null ? "—" : cents(+x.bid)}</td><td class="num ${sgn(x.pnl)}">${usd(x.pnl)}</td>
    <td class="num ${sgn(x.clv)}">${x.clv == null ? "—" : (x.clv * 100).toFixed(1) + "¢"}</td>
    <td><button class="ghost" data-close="${esc(x.ticker)}">Sell</button></td></tr>`,
  );
  $("positions").innerHTML = table(
    ["Position", "Side", "Paid", "Bid now", "P&L", "CLV", ""],
    rows,
    "No open paper positions.",
  );
  $("log").innerHTML =
    (p.log || [])
      .slice(0, 40)
      .map(
        (l) =>
          `<div class="muted small">${new Date(l.ts * 1000).toLocaleString()} · ${esc(l.msg)}</div>`,
      )
      .join("") || `<div class="empty">Nothing yet.</div>`;
}
$("positions").onclick = async (e) => {
  const b = e.target.closest("[data-close]");
  if (!b) return;
  try {
    await api("/api/paper/close", { ticker: b.dataset.close });
    toast("Sold at the bid");
    loadPaper();
  } catch (err) {
    toast(err.message);
  }
};
$("reset").onclick = async () => {
  await api("/api/paper/reset", {});
  toast("Paper book reset");
  loadPaper();
};
$("auto-on").onchange = async (e) => {
  try {
    await api("/api/autopilot", { enabled: e.target.checked });
    loadPaper();
  } catch (err) {
    toast(err.message);
  }
};
$("auto-save").onclick = async () => {
  try {
    await api("/api/autopilot", {
      min_edge: String($("auto-edge").value / 100),
      max_trade_usd: String($("auto-trade").value),
      max_total_usd: String($("auto-total").value),
    });
    toast("Limits saved");
    loadPaper();
  } catch (err) {
    toast(err.message);
  }
};

// ---------- track record ----------
function renderRecord() {
  const t = S.slate?.track;
  if (!t) return;
  const T = t.total;
  $("rec-kpis").innerHTML = [
    ["Graded picks", T.graded],
    ["Win rate", T.graded ? pct(T.wins / T.graded) : "—"],
    ["P&L per contract", usd(T.pnl_per_contract)],
    ["Waiting to settle", T.pending],
  ]
    .map(([k, v]) => `<div class="stat"><span>${k}</span><b>${v}</b></div>`)
    .join("");
  const rows = t.buckets.map(
    (
      b,
    ) => `<tr><td>${esc(b.league.toUpperCase())}</td><td>${esc(b.kind)}</td><td>${esc(b.bucket)}</td>
    <td class="num">${b.n}</td><td class="num">${pct(b.hit)}</td><td class="num">${pct(b.avg_fair)}</td><td class="num">${cents(b.avg_price)}</td>
    <td class="num ${sgn(b.roi)}">${pct(b.roi, 1)}</td><td class="num ${sgn(b.clv)}">${b.clv == null ? "—" : (b.clv * 100).toFixed(1) + "¢"}</td></tr>`,
  );
  $("buckets").innerHTML = table(
    [
      "League",
      "Bet",
      "Edge",
      "Picks",
      "Hit",
      "We said",
      "Avg price",
      "ROI",
      "CLV",
    ],
    rows,
    "No graded picks yet. Results appear here as games finish.",
  );
}

// ---------- loading ----------
async function loadSlate() {
  try {
    S.slate = await api("/api/slate");
    renderGames();
    renderRecord();
  } catch (e) {
    feed(false, e.message);
  }
}
async function loadCrypto() {
  try {
    S.crypto = await api("/api/crypto");
    renderCrypto();
  } catch (e) {
    feed(false, e.message);
  }
}
async function loadPaper() {
  try {
    S.paper = await api("/api/paper");
    renderPaper();
  } catch (e) {
    feed(false, e.message);
  }
}
function feed(ok, msg) {
  $("feed-dot").className = "dot " + (ok ? "ok" : "bad");
  $("feed-txt").textContent = msg;
}
async function loadAll() {
  await Promise.all([loadSlate(), loadCrypto(), loadPaper()]);
  const errs = [...(S.slate?.errors || []), ...(S.crypto?.errors || [])];
  if (errs.length) feed(false, errs[0]);
  else
    feed(
      !!S.slate?.updated,
      S.slate?.updated
        ? `Games updated ${ago(S.slate.updated)} · crypto ${ago(S.crypto?.updated)}`
        : "First refresh running…",
    );
}
$("refresh").onclick = async () => {
  await api("/api/refresh", {});
  toast("Refreshing games and crypto…");
  setTimeout(loadAll, 8000);
};
loadAll();
setInterval(loadAll, 20000);
