// Trading Bot SPA — fetches the JSON API and renders each view.
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const TITLES = {overview: "Overview", trades: "Trades", stocks: "Stocks", predictions: "Predictions", lab: "Strategy Lab"};

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

async function loadTrades() {
  const t = await get("/api/trades");
  const cards = $("#trades-cards"), empty = $("#trades-empty");
  if ((t.positions || []).length === 0) {
    cards.innerHTML = "";
    empty.style.display = "block";
    empty.innerHTML = t.dry_run
      ? "Nothing is being traded yet. The bot is in <b>dry-run</b> (safety on) and every signal is currently <b>hold</b>, so no positions exist. Turn off dry-run or place a trade and it appears here with entry price, time, and reason."
      : "No open positions right now.";
  } else {
    empty.style.display = "none";
    cards.innerHTML = t.positions.map(p => {
      const up = p.pl >= 0;
      return `<div class="trade-card">
        <div class="sym">${p.symbol}</div>
        <div class="meta"><b>${p.qty}</b> shares · entry <b>$${p.entry}</b> · now <b>$${p.price}</b>
          <div class="why">why: strategy entry signal</div></div>
        <div class="pl ${up ? "pos-up" : "pos-down"}">${up ? "+" : ""}$${p.pl}<br>
          <span style="font-size:12px">${up ? "+" : ""}${p.pl_pct}%</span></div>
      </div>`;
    }).join("");
  }
  $("#orders-table tbody").innerHTML = (t.orders || []).length ? t.orders.map(o =>
    `<tr><td>${o.symbol}</td><td class="${o.side}">${o.side.toUpperCase()}</td><td>${o.qty}</td>
     <td><span class="badge ${o.status}">${o.status}</span></td><td>${o.submitted}</td>
     <td>${o.filled_price ? "$" + o.filled_price : "—"}</td></tr>`
  ).join("") : `<tr><td colspan=6 style="color:var(--muted)">no orders yet</td></tr>`;
}

const cents = p => Math.round((p || 0) * 100) + "¢";
const tagClass = s => /LOCKED/.test(s) ? "locked" : /STRONG/.test(s) ? "strong" : "lean";

function topCard(r, i) {
  const side = (r.best_side || "").toLowerCase();
  const price = r.best_side === "YES" ? r.yes_price : r.no_price;
  const stake = 14, wins = price ? Math.round(stake / price) : 0;
  return `<div class="bet">
    <div class="rank">${i + 1}</div>
    <div class="side ${side}">${r.best_side}</div>
    <div class="loc">on <b>${r.city} ${r.threshold_c}°</b> · ${r.date_str}</div>
    <div class="q">${r.question}</div>
    <div class="stats">
      <div class="stat"><div class="k">Win chance</div><div class="v g">${Math.round((r.p_win || 0) * 100)}%</div></div>
      <div class="stat"><div class="k">Price</div><div class="v">${cents(price)}</div></div>
      <div class="stat"><div class="k">$${stake} → wins</div><div class="v g">$${wins}</div></div>
    </div>
    <a class="btn" href="${r.poly_url}" target="_blank">Place ${r.best_side} bet on Polymarket →</a>
  </div>`;
}

function pickCard(r) {
  const side = (r.best_side || "").toLowerCase();
  const pWin = Math.round((r.p_win || 0) * 100);
  const pMkt = Math.round((r.p_market || 0) * 100);
  const gap = Math.abs(pWin - pMkt);
  return `<div class="pick">
    <div class="top">
      <div><span class="side ${side}">${r.best_side}</span>
        <div><span class="tag ${tagClass(r.signal)}">${r.signal}</span>
        <span class="muted" style="font-size:12px"> · edge ${cents(r.edge)}</span></div></div>
      <div class="kelly"><div class="amt">$${r.bet_usd}</div><div class="lbl">Kelly bet</div></div>
    </div>
    <div class="q">${r.question}</div>
    <div class="gapbar">
      <div class="lbls"><span>Our predicted win chance <b>${pWin}%</b></span><span>Market thinks <b>${pMkt}%</b></span></div>
      <div class="gaptrack"><div class="gapfill" style="width:${pWin}%"></div><div class="gapmark" style="left:${pMkt}%"></div></div>
      <div class="gap-note">Gap of <b>${gap} points</b> = the edge</div>
    </div>
    <div class="wx">
      <span>market needs <b>${r.threshold_c}°</b></span>
      <span>today so far <b>${r.high_so_far_c ?? "—"}°</b></span>
      <span>today forecast <b>${r.today_forecast_c ?? "—"}°</b></span>
      <span>tomorrow <b>${r.tomorrow_forecast_c ?? "—"}°</b></span>
      <span><a class="mkt" href="${r.poly_url}" target="_blank">open market →</a></span>
    </div>
  </div>`;
}

async function loadPredictions() {
  $("#top-cards").innerHTML = `<div class="muted">loading live forecasts + markets…</div>`;
  const d = await get("/api/weather-edge");
  if (d.error) { $("#top-cards").innerHTML = `<div class="muted">${d.error}</div>`; return; }
  const c = d.counts || {};
  $("#edge-sub").textContent = `(win chance ≥ 90%)`;
  $("#picks-sub").textContent = `⭐ ${c.top || 0} top · ${c.liquid || 0} liquid · ${c.total || 0} signals total`;
  $("#top-cards").innerHTML = (d.top || []).length
    ? d.top.map(topCard).join("")
    : `<div class="muted">No ≥90% bets right now. See all picks below.</div>`;
  $("#pick-cards").innerHTML = (d.picks || []).map(pickCard).join("")
    || `<div class="muted">No actionable edges found this scan.</div>`;
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

const LOADERS = {overview: loadOverview, trades: loadTrades, stocks: loadStocks, predictions: loadPredictions, lab: loadLab};
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
