// Trading Bot SPA — fetches the JSON API and renders each view.
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const TITLES = {overview: "Overview", trades: "Trades", stocks: "Stocks", predictions: "Weather edge", markets: "All markets", lab: "Strategy Lab"};

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

// inline SVG sparkline; green if series rose over the window, red if it fell
function sparkline(vals, w = 240, h = 46) {
  if (!vals || vals.length < 2) return "";
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const x = i => (i / (vals.length - 1)) * w;
  const y = v => h - 4 - ((v - min) / span) * (h - 8);
  const pts = vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  const col = up ? "var(--green)" : "var(--red)";
  const area = `M0,${h} L${vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" L")} L${w},${h} Z`;
  const gid = "g" + Math.floor(x(vals[0]) * 1000) + vals.length;
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none">
    <defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="${col}" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    <path d="${area}" fill="url(#${gid})"/>
    <polyline points="${pts}" fill="none" stroke="${col}" stroke-width="2"
      stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

function stockCard(r) {
  const up = r.change >= 0;
  const sig = (r.signal || "hold");
  const p = r.plan || {};
  const actionable = sig === "buy" || sig === "sell";
  // the trade plan the strategy would execute (or is waiting to)
  const plan = `<div class="plan">
      <div class="p"><div class="k">Size</div><div class="v">${p.qty || 0} sh</div></div>
      <div class="p"><div class="k">≈ Amount</div><div class="v">$${Number(p.dollars || 0).toLocaleString()}</div></div>
      <div class="p"><div class="k">Stop ${p.stop_pct}%</div><div class="v stop">$${p.stop || 0}</div></div>
      <div class="p"><div class="k">Risk</div><div class="v risk">$${Number(p.risk || 0).toLocaleString()}</div></div>
    </div>`;
  const line = actionable
    ? `<div class="planline">✅ <b>${sig.toUpperCase()} ${p.qty} ${r.symbol}</b> now · exit if it drops to <b>$${p.stop}</b></div>`
    : `<div class="planline">⏸ Waiting. If it triggers, plan is <b>buy ${p.qty} @ ~$${r.price}</b>, stop <b>$${p.stop}</b> (risk $${Number(p.risk || 0).toLocaleString()})</div>`;
  return `<div class="stock ${sig}">
    <div class="row1">
      <div>
        <div class="sym">${r.symbol}</div>
        <div class="action ${sig}">${sig === "hold" ? "HOLD" : sig.toUpperCase()}</div>
      </div>
      <div style="text-align:right">
        <div class="price">$${Number(r.price).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
        <div class="chg ${up ? "up" : "down"}">${up ? "▲" : "▼"} ${up ? "+" : ""}${r.change}%</div>
      </div>
    </div>
    <div class="spark">${sparkline(r.spark)}</div>
    <div class="why"><span class="trend-dot ${r.above200 ? "up" : "down"}"></span>${r.why || ""}</div>
    ${plan}
    ${line}
    <button class="ai-btn" onclick="runAgent('${r.symbol}','stock','Current price about $${r.price}.', this)">🧠 Ask the AI analyst</button>
    <div class="ai-out"></div>
  </div>`;
}

// on-demand AI analyst — calls the Claude agent (web search + reasoning)
async function runAgent(subject, kind, context, btn) {
  const out = btn.parentElement.querySelector(".ai-out");
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "🧠 Researching live… (~30s)";
  out.innerHTML = "";
  try {
    const url = `/api/agent?subject=${encodeURIComponent(subject)}&kind=${kind}&context=${encodeURIComponent(context || "")}`;
    const d = await (await fetch(url)).json();
    if (d.error) {
      out.innerHTML = `<div class="ai-card err">⚠ ${d.error}${d.raw ? "<br><small>" + d.raw + "</small>" : ""}</div>`;
    } else {
      const dir = (d.direction || "hold").toLowerCase();
      const conf = Math.round((d.confidence || 0) * 100);
      const findings = (d.findings || []).map(f => `<li>${f}</li>`).join("");
      out.innerHTML = `<div class="ai-card">
        <div class="ai-head"><span class="ai-dir ${dir}">${dir.toUpperCase()}</span>
          <span class="ai-conf">${conf}% confidence</span></div>
        <div class="ai-rat">${d.rationale || ""}</div>
        ${findings ? `<ul class="ai-find">${findings}</ul>` : ""}
        <div class="ai-model">via ${d.model || "Claude"}</div>
      </div>`;
    }
  } catch (e) {
    out.innerHTML = `<div class="ai-card err">⚠ ${e}</div>`;
  }
  btn.disabled = false;
  btn.textContent = label;
}
window.runAgent = runAgent;

async function loadStocks() {
  $("#stock-cards").innerHTML = `<div class="muted">loading prices…</div>`;
  const s = await get("/api/signals");
  const rows = s.rows || [];
  const active = rows.filter(r => r.signal === "buy" || r.signal === "sell").length;
  $("#stk-sub").textContent = `${rows.length} tracked · ${active} with an active signal · ${rows.length - active} holding`;
  $("#stock-cards").innerHTML = rows.length
    ? rows.map(stockCard).join("")
    : `<div class="muted">${s.error || "no data"}</div>`;
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
    empty.className = "empty-state";
    empty.innerHTML = t.dry_run
      ? `<div class="ico">🛡️</div><b>No open positions — safety is on</b>
         <div style="margin-top:8px;max-width:520px;margin-inline:auto">The bot is in <b>dry-run</b> and every signal is currently <b>hold</b>, so nothing has been bought.
         The moment a trade fires (or you switch off dry-run), it lands here as a live card with entry, current price, and P/L.</div>`
      : `<div class="ico">💤</div><b>No open positions right now.</b>`;
  } else {
    empty.style.display = "none";
    cards.innerHTML = t.positions.map(p => {
      const up = p.pl >= 0;
      return `<div class="trade-card ${up ? "win" : "lose"}">
        <div class="thead">
          <div><div class="sym">${p.symbol}</div><div class="qty">${p.qty} shares held</div></div>
          <div class="pl ${up ? "pos-up" : "pos-down"}">${up ? "+" : ""}$${p.pl}
            <span class="pct">${up ? "+" : ""}${p.pl_pct}%</span></div>
        </div>
        <div class="levels">
          <div class="lv"><div class="k">Entry</div><div class="v">$${p.entry}</div></div>
          <div class="lv"><div class="k">Now</div><div class="v">$${p.price}</div></div>
          <div class="lv"><div class="k">Value</div><div class="v">$${Number(p.value).toLocaleString()}</div></div>
        </div>
      </div>`;
    }).join("");
  }
  $("#orders-table tbody").innerHTML = (t.orders || []).length ? t.orders.map(o =>
    `<tr><td>${o.symbol}</td><td class="${o.side}">${o.side.toUpperCase()}</td><td>${o.qty}</td>
     <td><span class="badge ${o.status}">${o.status}</span></td><td>${o.submitted}</td>
     <td>${o.filled_price ? "$" + o.filled_price : "—"}</td></tr>`
  ).join("") : `<tr><td colspan=6 style="color:var(--muted)">no orders yet</td></tr>`;
}

// escape a string for use inside a single-quoted JS arg within a double-quoted HTML attribute
const attr = s => String(s).replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/"/g, "&quot;");
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
  const model = Math.round((r.model_prob != null ? (side === "yes" ? r.model_prob : 1 - r.model_prob) : r.p_win) * 100);
  const pMkt = Math.round((r.p_market || 0) * 100);
  const gap = Math.abs(model - pMkt);
  const stn = r.station_confirmed
    ? `<span class="station ok">✓ resolution station</span>`
    : `<span class="station approx">~ approx location</span>`;
  return `<div class="pick">
    <div class="top">
      <div><span class="side ${side}">${r.best_side}</span>
        <div style="margin-top:4px">${stn}
        <span class="ens"> · ${r.members} GFS members · ${r.lead_days}d out</span></div></div>
      <div class="kelly"><div class="amt">$${r.bet_usd}</div><div class="lbl">¼-Kelly maker bet</div></div>
    </div>
    <div class="q">${r.question}</div>
    <div class="gapbar">
      <div class="lbls"><span>Ensemble model <b>${model}%</b></span><span>Market price <b>${pMkt}%</b></span></div>
      <div class="gaptrack"><div class="gapfill" style="width:${model}%"></div><div class="gapmark" style="left:${pMkt}%"></div></div>
      <div class="gap-note">Edge <b>${cents(r.edge)}</b> — the model sees ~${gap} points the market doesn't</div>
    </div>
    <div class="wx">
      <span>market needs <b>${r.threshold_c}°</b></span>
      <span>observed so far <b>${r.high_so_far_c ?? "—"}°</b></span>
      <span>volume <b>$${Number(r.volume_usd || 0).toLocaleString()}</b></span>
      <span><a class="mkt" href="${r.poly_url}" target="_blank">open market →</a></span>
    </div>
    <button class="ai-btn" onclick="runAgent('${attr(r.question)}','prediction','${attr('Market prices yes ' + (r.yes_price || '?') + '. Our GFS ensemble says model win-prob ' + model + '% for ' + r.best_side + '.')}', this)">🧠 Ask the AI analyst</button>
    <div class="ai-out"></div>
  </div>`;
}

async function loadPredictions() {
  $("#pick-cards").innerHTML = `<div class="muted">pulling live markets + 31-member GFS ensemble…</div>`;
  $("#watch-cards").innerHTML = "";
  const d = await get("/api/weather-edge");
  if (d.error) { $("#pick-cards").innerHTML = `<div class="muted">${d.error}</div>`; return; }
  const c = d.counts || {}, L = d.ledger || {};
  $("#picks-sub").textContent = `${c.actionable || 0} actionable · ${c.liquid || 0} liquid · ${c.total || 0} scanned`;
  $("#ledger-banner").innerHTML = `
    <div class="lstat"><div class="k">Bets logged</div><div class="v">${L.logged ?? 0}</div></div>
    <div class="lstat"><div class="k">Resolved</div><div class="v">${L.resolved ?? 0}</div></div>
    <div class="lstat"><div class="k">Win rate</div><div class="v">${L.win_rate != null ? L.win_rate + "%" : "—"}</div></div>
    <div class="lstat"><div class="k">Avg edge</div><div class="v">${L.avg_edge != null ? Math.round(L.avg_edge * 100) + "¢" : "—"}</div></div>
    <div class="lnote">${L.note || ""}</div>`;
  $("#pick-cards").innerHTML = (d.picks || []).length
    ? d.picks.map(pickCard).join("")
    : `<div class="muted">No actionable edges this scan — that's normal. The model only fires on liquid, near-term, maker-fittable mispricings. Fewer, better signals.</div>`;
  $("#watch-cards").innerHTML = (d.watch || []).map(r => `
    <div class="watch-row"><span class="side ${(r.best_side || "").toLowerCase()}" style="font-size:14px">${r.best_side || "—"}</span>
      <span class="wq">${r.question}</span>
      <span class="we">${r.model_prob != null ? Math.round(r.model_prob * 100) + "% model" : ""} vs ${Math.round((r.p_market || 0) * 100)}% mkt</span>
      <span class="muted">edge ${cents(r.edge || 0)}</span></div>`).join("")
    || `<div class="muted">nothing on the watchlist</div>`;
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

function marketCard(m) {
  const odds = (m.pairs || []).map(p => `<span class="oc">${p[0]} <b>${Math.round(p[1] * 100)}%</b></span>`).join("");
  return `<div class="mkt">
    <div class="mq"><a class="mkt" href="${m.url}" target="_blank" style="color:inherit;text-decoration:none">${m.question}</a></div>
    <div class="mmeta">${m.category ? `<span class="mcat">${m.category}</span>` : ""}
      <span>vol $${Number(m.volume).toLocaleString()}</span>${m.end ? `<span>ends ${m.end}</span>` : ""}</div>
    <div class="odds">${odds}</div>
    <button class="ai-btn" onclick="runAgent('${attr(m.question)}','prediction','${attr('Market odds: ' + (m.pairs || []).map(p => p[0] + ' ' + Math.round(p[1] * 100) + '%').join(', ') + '.')}', this)">🧠 Ask the AI analyst</button>
    <div class="ai-out"></div>
  </div>`;
}

let mktLoaded = false;
async function loadMarkets(force) {
  if (mktLoaded && !force) return;
  mktLoaded = true;
  const cards = $("#mkt-cards");
  cards.className = "mkt-grid";
  cards.innerHTML = `<div class="muted">loading Polymarket…</div>`;
  const q = ($("#mkt-q").value || "").trim();
  const d = await get("/api/markets" + (q ? "?q=" + encodeURIComponent(q) : ""));
  if (d.error) { cards.innerHTML = `<div class="muted">${d.error}</div>`; return; }
  $("#mkt-sub").textContent = `${(d.rows || []).length} markets${q ? ' matching "' + q + '"' : ' (most active)'}`;
  cards.innerHTML = (d.rows || []).map(marketCard).join("") || `<div class="muted">no markets found</div>`;
}

const LOADERS = {overview: loadOverview, trades: loadTrades, stocks: loadStocks, predictions: loadPredictions, markets: () => loadMarkets(false), lab: loadLab};
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
$("#mkt-go").onclick = () => loadMarkets(true);
$("#mkt-q").addEventListener("keydown", e => { if (e.key === "Enter") loadMarkets(true); });

// initial load + auto-refresh the active view every 30s
show("overview");
setInterval(() => show(current), 30000);
