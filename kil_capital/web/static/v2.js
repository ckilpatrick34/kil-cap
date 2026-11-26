// Kil Capital — simple dashboard.  Paper trading only; never sends real orders.
const $ = (s) => document.querySelector(s);
const TOKEN = window.KIL_TOKEN;

async function api(path, opts = {}) {
  const o = {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      "X-Kil-Token": TOKEN,
      ...(opts.headers || {}),
    },
  };
  const r = await fetch(path, o);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || j.error || r.statusText);
  return j;
}
const post = (p, body) =>
  api(p, { method: "POST", body: JSON.stringify(body || {}) });

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (x) =>
  x === null || x === undefined || x === "" ? null : Number(x);
const cents = (x) => {
  const n = num(x);
  return n === null ? "—" : `${Math.round(n * 100)}¢`;
};
const usd = (x) => {
  const n = num(x);
  return n === null
    ? "—"
    : (n < 0 ? "-$" : "$") +
        Math.abs(n).toLocaleString(undefined, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        });
};
const signed = (x) => {
  const n = num(x);
  return n === null ? "—" : (n > 0 ? "+" : "") + usd(n);
};
const cls = (x) => (num(x) > 0 ? "up" : num(x) < 0 ? "down" : "");
function px(m, k) {
  const d = m[`${k}_dollars`];
  if (d !== undefined && d !== null && d !== "") return Number(d);
  const c = m[k];
  return c === undefined || c === null ? null : Number(c) / 100;
}
function ago(ts) {
  if (!ts) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 60 ? `${s}s ago` : `${Math.round(s / 60)}m ago`;
}
function until(iso) {
  if (!iso) return "—";
  const s = (new Date(iso) - Date.now()) / 1000;
  if (s <= 0) return "closed";
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m`;
  if (s < 86400)
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.round(s / 86400)}d`;
}
function toast(msg, err) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 3500);
}

// ---- signals --------------------------------------------------------------------------------
let OPPS = [],
  sigFilter = "all",
  lastScan = null;
async function loadSignals() {
  try {
    const d = await api("/api/opportunities?limit=80");
    OPPS = d.opportunities;
    lastScan = d.last_scan_ts;
    renderSignals();
  } catch (e) {
    /* feed pill shows the error */
  }
}
function renderSignals() {
  let list = OPPS;
  if (sigFilter === "tested")
    list = list.filter((o) => (o.verdict || "").startsWith("PASS"));
  if (sigFilter === "new") list = list.filter((o) => !o.held);
  $("#sigsub").textContent = lastScan
    ? `${OPPS.length} signals · scanned ${ago(lastScan)} · best edge first`
    : "Waiting for the first market scan (about a minute)…";
  if (!list.length) {
    $("#signals").innerHTML =
      `<div class="empty">${OPPS.length ? "No signals match this filter." : "No signals right now. The bots scan every 45 seconds."}</div>`;
    return;
  }
  $("#signals").innerHTML = list
    .slice(0, 25)
    .map((o, i) => {
      const now =
        o.side === "yes"
          ? num(o.yes_ask)
          : num(o.yes_bid) === null
            ? null
            : 1 - num(o.yes_bid);
      const passed = (o.verdict || "").startsWith("PASS");
      return `<div class="sig" data-i="${OPPS.indexOf(o)}">
      <div class="action ${o.side}">BUY ${o.side.toUpperCase()}<small>at ${cents(o.price)}</small></div>
      <div class="what">
        <div class="title">${esc(o.title || o.ticker)}${o.sub_title ? ` <span class="muted">· ${esc(o.sub_title)}</span>` : ""}</div>
        <div class="why">${esc(o.strategy)}<span class="badge ${passed ? "pass" : ""}">${passed ? "backtest passed" : "untested"}</span>${o.held ? '<span class="badge held">holding</span>' : ""} · ${esc(o.reason || "")}</div>
      </div>
      <div class="nums">
        <div><span>Now</span><b>${cents(now)}</b></div>
        <div><span>Fair</span><b>${cents(o.fair)}</b></div>
        <div><span>Edge</span><b class="edge">${o.edge ? "+" + cents(o.edge) : "—"}</b></div>
        <div><span>Closes</span><b>${until(o.close_time)}</b></div>
      </div>
      <div class="go"><button class="btn small ${o.side}" data-buy="${OPPS.indexOf(o)}" ${o.paper_count ? "" : "disabled"}>Paper buy ${o.paper_count || ""}</button></div>
    </div>`;
    })
    .join("");
}
$("#signals").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-buy]");
  if (b) {
    e.stopPropagation();
    const o = OPPS[+b.dataset.buy];
    b.disabled = true;
    try {
      const r = await post("/api/paper/buy", {
        ticker: o.ticker,
        side: o.side,
        count: o.paper_count,
        strategy_id: o.strategy_id,
        fair: o.fair,
      });
      toast(
        `Paper bought ${r.count} ${r.side.toUpperCase()} at ${cents(r.price)}`,
      );
      loadPaper();
      loadSignals();
    } catch (err) {
      toast(err.message, true);
      b.disabled = false;
    }
    return;
  }
  const row = e.target.closest(".sig");
  if (row) openDrawer(OPPS[+row.dataset.i].ticker, OPPS[+row.dataset.i]);
});
$("#sigfilter").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  sigFilter = b.dataset.f;
  document
    .querySelectorAll("#sigfilter button")
    .forEach((x) => x.classList.toggle("on", x === b));
  renderSignals();
});

// ---- live markets ---------------------------------------------------------------------------
let PREV = {},
  deskFilled = false;
async function loadMarkets() {
  const q = encodeURIComponent($("#q").value.trim()),
    desk = encodeURIComponent($("#desk").value);
  try {
    const d = await api(`/api/markets?limit=150&q=${q}&desk=${desk}`);
    if (!deskFilled) {
      $("#desk").innerHTML += d.desks
        .map((x) => `<option>${esc(x)}</option>`)
        .join("");
      deskFilled = true;
    }
    setFeed(true, d.last_ok);
    const rows = d.markets.map((m) => {
      const yb = px(m, "yes_bid"),
        ya = px(m, "yes_ask");
      const no = yb === null ? null : 1 - yb;
      const prev = PREV[m.ticker];
      PREV[m.ticker] = ya;
      const fl =
        prev === undefined || prev === null || ya === null || prev === ya
          ? ""
          : ya > prev
            ? "flash-up"
            : "flash-down";
      return `<tr data-t="${esc(m.ticker)}"><td><div class="t">${esc(m.title)}</div><div class="st">${esc(m.yes_sub_title || m.ticker)}</div></td>
        <td class="r"><span class="px yes ${fl}">${cents(ya)}</span></td><td class="r"><span class="px no ${fl}">${cents(no)}</span></td>
        <td class="r">${num(m.volume_24h ?? m.volume)?.toLocaleString() ?? "—"}</td><td class="r">${until(m.close_time)}</td></tr>`;
    });
    $("#mktbody").innerHTML =
      rows.join("") ||
      `<tr><td colspan="5" class="empty">No markets match.</td></tr>`;
    $("#mktsub").textContent =
      `${d.markets.length} markets · most traded first · prices ${ago(d.last_ok)}`;
  } catch (e) {
    setFeed(false, null, e.message);
    $("#mktbody").innerHTML =
      `<tr><td colspan="5" class="empty">Can't reach Kalshi: ${esc(e.message)}</td></tr>`;
  }
}
let qTimer;
$("#q").addEventListener("input", () => {
  clearTimeout(qTimer);
  qTimer = setTimeout(loadMarkets, 300);
});
$("#desk").addEventListener("change", loadMarkets);
$("#mktbody").addEventListener("click", (e) => {
  const r = e.target.closest("tr[data-t]");
  if (r) openDrawer(r.dataset.t);
});

function setFeed(ok, lastOk, err) {
  const p = $("#feed");
  p.className = "pill " + (ok ? "live" : "down");
  $("#feedtxt").textContent = ok
    ? `Live Kalshi prices · ${ago(lastOk)}`
    : `Kalshi offline${err ? ": " + err.slice(0, 50) : ""}`;
}

// ---- paper portfolio + autopilot -------------------------------------------------------------
let AUTO = null,
  settingsDirty = false;
async function loadPaper() {
  try {
    const d = await api("/api/paper");
    $("#equity").textContent = usd(d.equity);
    const tp = $("#totalpnl");
    tp.textContent = signed(d.total_pnl);
    tp.className = cls(d.total_pnl);
    $("#cash").textContent = usd(d.cash);
    $("#atrisk").textContent = usd(d.at_risk);
    const u = $("#unreal");
    u.textContent = signed(d.unrealized);
    u.className = cls(d.unrealized);
    const r = $("#real");
    r.textContent = signed(d.realized);
    r.className = cls(d.realized);
    $("#pfsub").textContent = d.closed_trades
      ? `${d.closed_trades} closed trades · ${d.wins} winners`
      : `Started with ${usd(d.start_cash)} of pretend money.`;
    $("#positions").innerHTML = d.positions.length
      ? d.positions
          .map(
            (p) => `
      <div class="pos-row"><div><div class="t">${esc(p.title || p.ticker)}</div>
        <div class="d">${p.count} ${p.side.toUpperCase()} @ ${cents(p.avg_price)} · now ${cents(p.bid)} · ${esc(p.strategy_id)}</div></div>
        <div class="right"><b class="${cls(p.pnl)}">${signed(p.pnl)}</b><button class="btn ghost small" data-close="${esc(p.ticker)}">Sell</button></div></div>`,
          )
          .join("")
      : `<div class="empty">No open paper positions.</div>`;
    $("#log").innerHTML = d.log.length
      ? d.log
          .map(
            (l) =>
              `<li><time>${new Date(l.ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</time>${esc(l.msg)}</li>`,
          )
          .join("")
      : `<li class="muted">Nothing yet.</li>`;
    AUTO = d.autopilot;
    renderAuto(d);
  } catch (e) {
    /* ignore */
  }
}
function renderAuto(d) {
  const a = AUTO;
  $("#autotoggle").checked = a.enabled;
  const st = $("#autostate");
  st.className = "autostate " + (a.enabled ? "on" : "off");
  st.textContent = a.enabled
    ? `On. Paper-buying signals with edge ≥ ${Math.round(a.min_edge * 100)}¢. ${d.positions.length}/${a.max_positions} positions · ${usd(d.at_risk)} of ${usd(a.max_total_usd)} used. Last scan ${ago(d.last_scan_ts)}.`
    : "Off. Turn it on to let the bot paper-trade the signals.";
  if (!settingsDirty) {
    $("#a_edge").value = Math.round(a.min_edge * 100);
    $("#a_trade").value = Number(a.max_trade_usd);
    $("#a_total").value = Number(a.max_total_usd);
    $("#a_pos").value = a.max_positions;
  }
}
["#a_edge", "#a_trade", "#a_total", "#a_pos"].forEach((s) =>
  $(s).addEventListener("input", () => (settingsDirty = true)),
);
function limits() {
  return {
    min_edge: String(Math.max(1, +$("#a_edge").value) / 100),
    max_trade_usd: String(+$("#a_trade").value),
    max_total_usd: String(+$("#a_total").value),
    max_positions: Math.round(+$("#a_pos").value),
  };
}
$("#autotoggle").addEventListener("change", async (e) => {
  const on = e.target.checked;
  try {
    await post("/api/autopilot", { enabled: on, ...limits() });
    settingsDirty = false;
    toast(on ? "Autopilot on (paper money)" : "Autopilot off");
  } catch (err) {
    e.target.checked = !on;
    toast(err.message, true);
  }
  setTimeout(loadPaper, 600);
});
$("#savesettings").addEventListener("click", async () => {
  try {
    await post("/api/autopilot", limits());
    settingsDirty = false;
    toast("Limits saved");
    loadPaper();
  } catch (err) {
    toast(err.message, true);
  }
});
$("#positions").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-close]");
  if (!b) return;
  b.disabled = true;
  try {
    const r = await post("/api/paper/close", { ticker: b.dataset.close });
    toast(`Sold at ${cents(r.price)} · ${signed(r.pnl)}`);
    loadPaper();
  } catch (err) {
    toast(err.message, true);
    b.disabled = false;
  }
});
$("#reset").addEventListener("click", async () => {
  if (!confirmReset()) return;
  try {
    await post("/api/paper/reset");
    toast("Paper account reset");
    loadPaper();
  } catch (err) {
    toast(err.message, true);
  }
});
let resetArmed = 0;
function confirmReset() {
  // two clicks within 3s instead of a browser dialog
  if (Date.now() - resetArmed < 3000) return true;
  resetArmed = Date.now();
  $("#reset").textContent = "Click again";
  setTimeout(() => ($("#reset").textContent = "Reset"), 3000);
  return false;
}

// ---- market drawer ------------------------------------------------------------------------------
let DT = null,
  dTimer = null;
async function openDrawer(ticker, opp) {
  DT = ticker;
  $("#drawer").classList.remove("hidden");
  $("#d_title").textContent = opp?.title || ticker;
  $("#d_sub").textContent = "";
  $("#d_desk").textContent = ticker;
  $("#d_sig").innerHTML = opp
    ? `<div class="sigbox"><b>Signal: buy ${opp.side.toUpperCase()} up to ${cents(opp.price)}.</b>
    Fair value ${cents(opp.fair)}, edge ${opp.edge ? "+" + cents(opp.edge) : "—"}.<br><span class="muted">${esc(opp.strategy)} · ${esc(opp.reason || "")}</span></div>`
    : "";
  if (opp) $("#d_count").value = opp.paper_count || 10;
  refreshDrawer();
  clearInterval(dTimer);
  dTimer = setInterval(refreshDrawer, 3000);
}
async function refreshDrawer() {
  if (!DT) return;
  const t = DT;
  try {
    const [m, b] = await Promise.all([
      api(`/api/markets/${encodeURIComponent(t)}`),
      api(`/api/markets/${encodeURIComponent(t)}/book`),
    ]);
    if (t !== DT) return;
    $("#d_title").textContent = m.title || t;
    $("#d_sub").textContent = m.yes_sub_title || "";
    const yb = px(m, "yes_bid"),
      ya = px(m, "yes_ask");
    $("#d_yes").textContent = cents(ya);
    $("#d_no").textContent = yb === null ? "—" : cents(1 - yb);
    const side = (k) =>
      (b[`${k}_dollars`] || (b[k] || []).map(([p, q]) => [p / 100, q]))
        .map(([p, q]) => [Number(p), Number(q)])
        .sort((a, c) => c[0] - a[0])
        .slice(0, 8);
    const y = side("yes"),
      n = side("no");
    $("#d_book").innerHTML = Array.from(
      { length: Math.max(y.length, n.length, 1) },
      (_, i) =>
        `<tr><td class="up">${y[i] ? cents(y[i][0]) : ""}</td><td class="r">${y[i]?.[1] ?? ""}</td><td class="down">${n[i] ? cents(n[i][0]) : ""}</td><td class="r">${n[i]?.[1] ?? ""}</td></tr>`,
    ).join("");
    $("#d_meta").textContent =
      `Volume ${num(m.volume)?.toLocaleString() ?? "—"} · closes ${until(m.close_time)} · ${m.status || ""}`;
  } catch (e) {
    $("#d_meta").textContent = e.message;
  }
}
function closeDrawer() {
  DT = null;
  clearInterval(dTimer);
  $("#drawer").classList.add("hidden");
}
$("#dclose").addEventListener("click", closeDrawer);
$("#drawer").addEventListener("click", (e) => {
  if (e.target.id === "drawer") closeDrawer();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDrawer();
});
async function drawerBuy(side) {
  try {
    const r = await post("/api/paper/buy", {
      ticker: DT,
      side,
      count: Math.max(1, +$("#d_count").value),
    });
    toast(`Paper bought ${r.count} ${side.toUpperCase()} at ${cents(r.price)}`);
    loadPaper();
  } catch (err) {
    toast(err.message, true);
  }
}
$("#d_buyyes").addEventListener("click", () => drawerBuy("yes"));
$("#d_buyno").addEventListener("click", () => drawerBuy("no"));

// ---- loop ------------------------------------------------------------------------------------
loadSignals();
loadMarkets();
loadPaper();
setInterval(loadSignals, 5000);
setInterval(loadMarkets, 6000);
setInterval(loadPaper, 4000);
