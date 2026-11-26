// Live tab: in-game picks from the live model (kil_capital/sports/live.py). Uses app.js globals.
// Recommend-only. Prices are a snapshot from the last rebuild, so each pick says the most it is worth paying.
"use strict";

document.head.insertAdjacentHTML(
  "beforeend",
  `<style>.lnote{padding:0 16px 14px;margin:0}.lcard{margin-top:12px;overflow-x:auto}
.lhead{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:14px 16px 4px;font-size:15px}
.lcard>p.small{padding:0 16px;margin:4px 0 8px}.ltab td,.ltab th{white-space:nowrap}</style>`,
);

window.renderLive = function renderLive() {
  const el = document.getElementById("live");
  if (!el || !S) return;
  const lg = F.league;
  const games = (S.games || []).filter(
    (g) => g.state === "in" && (!lg || g.league === lg),
  );
  const cnt = document.getElementById("liveCount");
  if (cnt) cnt.textContent = games.length || "";
  if (!games.length) {
    el.innerHTML = `<p class="empty">No games in progress${lg ? " for " + esc(lg) : ""} right now. When one starts, it shows here with the model's in-game call on every Kalshi market for it.</p>`;
    return;
  }
  el.innerHTML = games.map(card).join("");
};

function card(g) {
  const v = g.live;
  const h = g.home || {},
    a = g.away || {};
  const score = `${esc(a.abbr || a.name)} <b class="num">${a.score ?? "–"}</b> @ ${esc(h.abbr || h.name)} <b class="num">${h.score ?? "–"}</b>`;
  const head = `<div class="lhead"><div><span class="tag">${esc(g.league)}</span>${score}</div><span class="muted small">${esc(g.detail || "")}</span></div>`;
  if (!v)
    return `<section class="panel lcard">${head}<p class="empty">No clock or score from ESPN yet, so no in-game price.</p></section>`;
  const pre = v.p_home_pre;
  const wp = `<p class="small muted">${esc(h.abbr || "Home")} win chance now <b class="num">${pct(v.p_home, 0)}</b>${pre == null ? "" : ` (pregame ${pct(pre, 0)})`} · ${pct(1 - v.frac_left, 0)} of the game played</p>`;
  const rows = v.rows.length
    ? `<table class="ltab"><thead><tr><th>Bet</th><th class="r">Now</th><th class="r">Buy at or under</th><th class="r">Edge</th><th>Call</th></tr></thead><tbody>${v.rows.map(row).join("")}</tbody></table>`
    : `<p class="empty">No live Kalshi prices for this game.</p>`;
  return `<section class="panel lcard">${head}${wp}${rows}</section>`;
}

function row(r) {
  const s =
    r.side === "yes"
      ? `<span class="side-yes">YES</span>`
      : `<span class="side-no">NO</span>`;
  const max = r.max_price == null ? "–" : cents(r.max_price);
  return `<tr title="${esc(LV_WHY[r.level] || "")}"><td>${s} ${esc(r.label)}</td><td class="r num">${cents(r.price)}</td>
    <td class="r num">${max}</td><td class="r num ${r.edge > 0 ? "pos" : "neg"}">${pct(r.edge, 1, true)}</td>
    <td><span class="lvl ${r.level}">${LV[r.level]}</span></td></tr>`;
}
