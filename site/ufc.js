// UFC tab: Kil Cap vs Vegas on every upcoming UFC fight, with a BET / No bet call.
// The goal is beating the sportsbooks; Kalshi is only where a bet gets placed.
// Data: state.json "ufc" block from kil_capital/ufc/desk.py. Uses app.js globals ($, esc, pct, cents, usd, startsIn).
// Recommend-only: nothing here places an order.
"use strict";

document.head.insertAdjacentHTML(
  "beforeend",
  `<style>.ufc-sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;padding:0 16px 14px}
.ufc-sum div{border:1px solid var(--line);border-radius:6px;padding:10px 12px}.ufc-sum span{display:block;font-size:12px;color:var(--muted)}
.ufc-sum b{font:700 22px/1.2 var(--disp,inherit);font-variant-numeric:tabular-nums}.ufc-sum small{display:block;font-size:12px;color:var(--muted)}
.ufc-ev{margin:18px 0 8px;font-size:15px}.ufc-ev .muted{font-weight:400}
.ufc .mu .tm b{font-size:19px}.ufc .mu{justify-content:space-between}.ufc .mu .tm:last-child{text-align:right}
.ufc .ln{grid-template-columns:auto 1fr 1fr}.ufc .why{font-size:13px;color:var(--muted)}
.ufc .pnums{grid-template-columns:repeat(3,minmax(0,1fr))}.ufc-note{padding:0 16px 14px;margin:0}</style>`,
);

const UFC_LV = { High: "high", Medium: "medium", Lean: "lean", Low: "low", Live: "live", Final: "low" };
const ufcMl = (v) => (v == null ? "–" : v > 0 ? `+${Math.round(v)}` : `${Math.round(v)}`);
const ufcLast = (n) => esc(String(n || "").split(" ").slice(-1)[0]);

window.renderUfc = function renderUfc() {
  const el = document.getElementById("ufc");
  if (!el || !S) return;
  const U = S.ufc;
  if (!U) {
    el.innerHTML = `<p class="empty">The UFC model has not run yet. It fills in on the next rebuild.</p>`;
    return;
  }
  const fights = U.fights || [];
  const bets = fights.filter((f) => f.pick?.label === "BET");
  const cnt = document.getElementById("ufcCount");
  if (cnt) cnt.textContent = bets.length || "";
  const bt = U.backtest || {}, rec = U.record || {};
  const r = (o) => (o?.n ? `${o.right}-${o.n - o.right} (${pct(o.right / o.n, 0)})` : "none yet");
  const sum = `<div class="ufc-sum">
    <div><span>Bets on this card</span><b>${bets.length}</b><small>${usd(bets.reduce((a, f) => a + (f.pick.stake || 0), 0), 2)} at risk, $10 max a bet</small></div>
    <div><span>Kil Cap vs Vegas, backtest</span><b>${pct(bt.model_right, 0)} vs ${pct(bt.vegas_right, 0)}</b><small>winners picked on ${bt.fights ?? "–"} unseen fights</small></div>
    <div><span>Kil Cap vs Vegas, live</span><b>${esc(r(rec.model))}</b><small>Vegas ${esc(r(rec.vegas))}</small></div>
    <div><span>Paper bets graded</span><b>${rec.bets?.n ? usd(rec.bets.pl, 2) : "–"}</b><small>${rec.bets?.n ? `${rec.bets.won}-${rec.bets.n - rec.bets.won} on ${usd(rec.bets.staked, 2)} staked` : "none settled yet"}</small></div>
  </div>
  <p class="small muted ufc-note">The goal is to beat the sportsbooks. Kalshi is only where the bet gets placed. Our model alone picks fewer winners than Vegas and lost about ${pct(-(bt.model_return ?? 0.1), 0)} betting against the closing line in the backtest, so the Vegas line is the bar. A <b>BET</b> appears only when Kalshi sells a fighter at least 3¢ cheaper than the Vegas fair price, after Kalshi's fee. Most fights will say <b>No bet</b>, and that is the point.</p>`;
  if (!fights.length) {
    el.innerHTML = sum + `<p class="empty">No UFC fights in the next two weeks.</p>`;
    return;
  }
  let html = sum, ev = null;
  for (const f of fights) {
    if (f.event !== ev) {
      if (ev !== null) html += `</div>`;
      ev = f.event;
      html += `<h3 class="ufc-ev">${esc(ev)} <span class="muted small">${f.start ? new Date(f.start).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) : ""}</span></h3><div class="pgrid">`;
    }
    html += ufcCard(f);
  }
  el.innerHTML = html + `</div>`;
};

function ufcCard(f) {
  const a = f.a, b = f.b, p = f.pick || {};
  const lv = UFC_LV[p.conf] || "low";
  const t = (x) => `<span class="tm"><b>${esc(x.name)}</b><small>${esc(x.record || "")} · UFC ${esc(x.ufc_record)}${x.age ? ` · ${Math.round(x.age)}y` : ""}</small></span>`;
  const hasV = a.vegas != null && b.vegas != null;
  const gap = hasV && f.vegas_p ? (a.p_model - f.vegas_p.a) : null;
  const gapTxt = gap == null ? "" : Math.abs(gap) < 0.005 ? "even" : `${pct(Math.abs(gap), 0)} more on ${gap > 0 ? ufcLast(a.name) : ufcLast(b.name)}`;
  const ln = `<div class="ln"><span class="kc">Kil Cap line</span><b class="kc">${ufcLast(a.name)} ${ufcMl(f.kil_line?.a)}</b><b class="kc">${ufcLast(b.name)} ${ufcMl(f.kil_line?.b)}</b>
    <span>Vegas line</span>${hasV ? `<b>${ufcLast(a.name)} ${ufcMl(a.vegas)}</b><b>${ufcLast(b.name)} ${ufcMl(b.vegas)}</b>` : `<em>not posted yet</em>`}
    <span>Place on Kalshi</span><i>${a.yes_ask != null ? cents(a.yes_ask) : "–"}</i><i>${b.yes_ask != null ? cents(b.yes_ask) : "–"}</i>${gap == null ? "" : `<span>Kil Cap vs Vegas</span><i style="grid-column:2/4">${gapTxt}</i>`}</div>`;
  const bet = p.label === "BET"
    ? `<b>BET: ${esc(p.name)} to win</b> <span class="muted">Place on Kalshi: buy <span class="side-yes">YES</span> at ${cents(p.price)}, ${p.contracts} contracts</span>`
    : `<b>No bet</b> <span class="muted">· our side: ${esc(p.name)}</span>`;
  const n = (k, v, cls = "") => `<span><small>${k}</small><b class="${cls}">${v}</b></span>`;
  return `<article class="pcard ufc ${lv}${p.label === "BET" ? " on" : ""}">
    <header><span class="tag">UFC</span><span class="muted small">${esc(f.wc || "")}${f.rounds ? ` · ${f.rounds} rds` : ""} · ${f.state === "pre" ? startsIn(f.start) : esc(f.status || "")}</span><span class="lvl ${lv}">${esc(p.conf || "")}</span></header>
    <div class="mu">${t(a)}<i>vs</i>${t(b)}</div>${ln}
    <div class="pbet">${bet}</div>
    <div class="pnums">${n("Win chance", pct(p.win_pct, 0), p.win_pct >= 0.55 ? "pos" : "")}${n("Edge vs Vegas", p.edge == null ? "–" : pct(p.edge, 1, true), p.edge == null ? "muted" : p.edge > 0 ? "pos" : "neg")}${n("Bet", p.label === "BET" ? usd(p.stake, 2) : "–", p.label === "BET" ? "" : "muted")}</div>
    <footer><span class="why">${esc(p.reason || "")}</span></footer>
  </article>`;
}
