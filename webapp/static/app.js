// Trading Bot SPA — fetches the JSON API and renders each view.
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const TITLES = {overview: "Overview", stocks: "Stocks", predictions: "Predictions", lab: "Strategy Lab"};

async function get(path) {
  try { const r = await fetch(path); return await r.json(); }
  catch (e) { return {error: String(e)}; }
}

function sigCell(s) {
  const cls = s === "buy" ? "buy" : s === "sell" ? "sell" : "hold";
  return `<td class="${cls}">${(s || "?").toUpperCase()}</td>`;
}

// horizontal bar chart for strategy returns
function barChart(el, rows, key, fmt, color) {
  const max = Math.max(...rows.map(r => Math.abs(r[key]))) || 1;
  el.innerHTML = rows.map(r => {
    const pct = Math.abs(r[key]) / max * 100;
    const c = typeof color === "function" ? color(r[key]) : color;
    return `<div class="bar-row"><div class="name">${r.name}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${c}"></div></div>
      <div class="bar-val">${fmt(r[key])}</div></div>`;
  }).join("");
}

async function loadOverview() {
  const o = await get("/api/overview");
  $("#ov-equity").textContent = o.online ? "$" + Number(o.equity).toLocaleString() : "offline";
  $("#ov-mode").textContent = (o.mode || "").toLowerCase();
  $("#ov-dry").textContent = o.dry_run ? "ON" : "OFF";
  $("#ov-dry").style.color = o.dry_run ? "var(--green)" : "var(--amber)";
  $("#ov-pos").textContent = o.positions;
  $("#mode-pill").textContent = o.mode + (o.dry_run ? " · DRY RUN" : " · LIVE ORDERS");
  const dot = $("#status-dot"), st = $("#status-text");
  dot.className = "dot " + (o.online ? "on" : "off");
  st.textContent = o.online ? "connected" : "offline";
  const poly = await get("/api/polymarket");
  $("#ov-poly").textContent = (poly.top || []).length + (poly.longshots || []).length;
  const strat = await get("/api/strategies");
  barChart($("#mini-chart"), strat.rows, "ret", v => v.toFixed(0) + "%",
           v => v >= 100 ? "var(--green)" : "var(--accent)");
}

async function loadStocks() {
  const s = await get("/api/signals");
  $("#sig-table tbody").innerHTML = (s.rows || []).map(r =>
    `<tr><td>${r.symbol}</td><td>$${Number(r.price).toLocaleString()}</td>${sigCell(r.signal)}</tr>`
  ).join("") || `<tr><td colspan=3>${s.error || "no data"}</td></tr>`;
  const p = await get("/api/positions");
  $("#pos-table tbody").innerHTML = (p.rows || []).length ? p.rows.map(r =>
    `<tr><td>${r.symbol}</td><td>${r.qty}</td><td>$${Number(r.value).toLocaleString()}</td>
     <td class="${r.pl >= 0 ? "pos-up" : "pos-down"}">${r.pl >= 0 ? "+" : ""}${r.pl}</td></tr>`
  ).join("") : `<tr><td colspan=4 style="color:var(--muted)">no open positions</td></tr>`;
}

async function loadPredictions() {
  const p = await get("/api/polymarket");
  $("#ls-table tbody").innerHTML = (p.longshots || []).map(r =>
    `<tr><td>${r.q}</td><td>${r.outcome}</td><td>${r.prob}</td></tr>`
  ).join("") || `<tr><td colspan=3 style="color:var(--muted)">none flagged</td></tr>`;
  $("#top-table tbody").innerHTML = (p.top || []).map(r =>
    `<tr><td>${r.q}</td><td>$${Number(r.vol).toLocaleString()}</td>
     <td>${r.pairs.map(x => x[0] + " " + x[1]).join(" / ")}</td></tr>`
  ).join("") || `<tr><td colspan=3>${p.error || "no data"}</td></tr>`;
}

async function loadLab() {
  const s = await get("/api/strategies");
  barChart($("#lab-chart"), s.rows, "ret", v => v.toFixed(1) + "%",
           v => v >= 100 ? "var(--green)" : "var(--accent)");
  $("#lab-table tbody").innerHTML = s.rows.map(r =>
    `<tr><td>${r.name}</td><td>+${r.ret}%</td>
     <td class="pos-down">${r.dd}%</td><td>${(r.ret / Math.abs(r.dd)).toFixed(2)}</td></tr>`
  ).join("");
}

const LOADERS = {overview: loadOverview, stocks: loadStocks, predictions: loadPredictions, lab: loadLab};
let current = "overview";

function show(view) {
  current = view;
  $$(".sidebar a").forEach(a => a.classList.toggle("active", a.dataset.view === view));
  $$(".view").forEach(v => v.classList.toggle("active", v.id === view));
  $("#view-title").textContent = TITLES[view];
  LOADERS[view]();
}

$$(".sidebar a").forEach(a => a.onclick = () => show(a.dataset.view));
$("#refresh").onclick = () => show(current);

// initial load + auto-refresh the active view every 30s
show("overview");
setInterval(() => show(current), 30000);
