// Trading Bot SPA — fetches the JSON API and renders each view.
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const TITLES = {overview: "Overview", trades: "Trades", stocks: "Stocks", predictions: "Weather edge", aipicks: "AI research", markets: "All markets", lab: "Strategy Lab"};

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
  // fast stuff first
  get("/api/overview").then(o => {
    $("#ov-equity").textContent = o.online ? "$" + Number(o.equity).toLocaleString() : "offline";
    $("#ov-mode").textContent = (o.mode || "").toLowerCase() + " account";
    $("#ov-dry").textContent = o.dry_run ? "ON" : "OFF";
    $("#ov-dry").style.color = o.dry_run ? "var(--green)" : "var(--amber)";
    $("#mode-pill").textContent = o.mode + (o.dry_run ? " · DRY RUN" : " · LIVE ORDERS");
    const dot = $("#status-dot"), st = $("#status-text");
    dot.className = "dot " + (o.online ? "on" : "off");
    st.textContent = o.online ? "connected" : "offline";
  });
  get("/api/strategies").then(s =>
    barChart($("#mini-chart"), s.rows || [], "ret", v => v.toFixed(0) + "%",
             v => v >= 100 ? "var(--green)" : "var(--accent)"));

  // stocks strip
  get("/api/signals").then(s => {
    $("#ov-stocks").innerHTML = (s.rows || []).map(r => {
      const up = r.change >= 0;
      return `<div class="ov-row"><span class="ov-sym">${r.symbol}</span>
        <span class="ov-mid">$${Number(r.price).toLocaleString()}</span>
        <span class="chg ${up ? "up" : "down"}">${up ? "+" : ""}${r.change}%</span>
        <span class="sig-badge ${r.signal}">${(r.signal || "?").toUpperCase()}</span></div>`;
    }).join("") || `<span class="muted">no data</span>`;
  });

  // top markets
  get("/api/markets").then(d => {
    $("#ov-markets").innerHTML = (d.rows || []).slice(0, 6).map(m =>
      `<div class="ov-row"><a class="ov-q" href="${m.url}" target="_blank">${esc(m.question)}</a>
        <span class="ov-odds">${(m.pairs && m.pairs[0] ? Math.round(m.pairs[0][1] * 100) + "%" : "")}</span></div>`
    ).join("") || `<span class="muted">no data</span>`;
  });

  // weather edges + track record + learning
  get("/api/weather-edge").then(d => {
    const L = d.ledger || {}, c = d.counts || {}, cal = d.calibration || {};
    $("#ov-edges").textContent = c.actionable ?? "—";
    $("#ov-logged").textContent = L.win_rate != null ? L.win_rate + "%" : "—";
    $("#ov-winrate").textContent = L.resolved ? `${L.wins}/${L.resolved} resolved` : "no bets settled yet";
    const picks = d.picks || [];
    $("#ov-weather").innerHTML = picks.length ? picks.slice(0, 5).map(r => {
      const model = Math.round((r.best_side === "YES" ? r.model_prob : 1 - r.model_prob) * 100);
      return `<div class="ov-row"><span class="side ${(r.best_side || "").toLowerCase()}">${r.best_side}</span>
        <a class="ov-q" href="${r.poly_url}" target="_blank">${r.city} ${r.threshold_c}°</a>
        <span class="ov-mid">${model}% vs ${Math.round(r.p_market * 100)}%</span>
        <span class="ov-edge">+${cents(r.edge)}</span></div>`;
    }).join("") : `<span class="muted">No actionable edges right now — the model only fires on real, liquid mispricings.</span>`;
    // track record area
    const bucketLine = (cal.buckets || []).map(b => `predicted ${b.predicted}% → won ${b.actual}%`).join("<br>");
    $("#ov-track").innerHTML = `
      <div class="ov-row"><span>Bets logged</span><span class="ov-mid">${L.logged ?? 0}</span></div>
      <div class="ov-row"><span>Resolved</span><span class="ov-mid">${L.resolved ?? 0}</span></div>
      <div class="ov-row"><span>Win rate</span><span class="ov-mid">${L.win_rate != null ? L.win_rate + "%" : "—"}</span></div>
      <div class="ov-row"><span>Calibration (Brier)</span><span class="ov-mid">${cal.brier != null ? cal.brier : "—"}</span></div>
      ${cal.resolved ? `<div class="muted" style="margin-top:8px;font-size:12px">${bucketLine}</div>`
        : `<div class="muted" style="margin-top:8px;font-size:12px">Learning kicks in once bets settle. Prove ~50-100 before real money.</div>`}`;
  });

  // AI research area
  get("/api/ai-picks").then(d => {
    const res = (d.results || []).slice().sort((a, b) => Math.abs(b.edge || 0) - Math.abs(a.edge || 0));
    if (d.running) {
      $("#ov-ai").innerHTML = `<span class="muted">researching world markets… ${d.done}/${d.total}</span>`;
    } else if (res.length) {
      $("#ov-ai").innerHTML = res.slice(0, 4).map(r => {
        const conf = Math.round((r.confidence || 0) * 100);
        const ed = r.edge != null ? Math.round(r.edge * 100) : null;
        return `<div class="ov-row"><span class="side ${(r.direction || "").toLowerCase() === "no" ? "no" : "yes"}">${(r.direction || "?").toUpperCase()}</span>
          <a class="ov-q" href="${r.url}" target="_blank">${esc(r.question)}</a>
          <span class="ov-mid">${conf}%</span>${ed != null ? `<span class="ov-edge">${ed > 0 ? "+" : ""}${ed}pt</span>` : ""}</div>`;
      }).join("");
    } else {
      $("#ov-ai").innerHTML = `<span class="muted">Not run yet — open the AI research tab and hit ‘Run’ to have Claude read live news on world markets.</span>`;
    }
  });
}

// inline SVG sparkline; green if series rose over the window, red if it fell
let sparkUID = 0;
function sparkline(vals, w = 240, h = 46) {
  if (!vals || vals.length < 2) return "";
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const x = i => (i / (vals.length - 1)) * w;
  const y = v => h - 4 - ((v - min) / span) * (h - 8);
  const pts = vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  const col = up ? "var(--green)" : "var(--red)";
  const area = `M0,${h} L${vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" L")} L${w},${h} Z`;
  const gid = "spark" + (++sparkUID);
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
// escape for safe insertion into HTML text/content (external market questions etc.)
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const cents = p => Math.round((p || 0) * 100) + "¢";
const tagClass = s => /LOCKED/.test(s) ? "locked" : /STRONG/.test(s) ? "strong" : "lean";

function topCard(r, i) {
  const side = (r.best_side || "").toLowerCase();
  const win = Math.round((side === "yes" ? r.model_prob : 1 - r.model_prob) * 100);
  const price = r.p_market || 0;
  const wins = price ? Math.round(10 / price) : 0;  // £10 stake payout
  return `<div class="bet ${side}">
    <div class="rank">${i + 1}</div>
    <div class="side ${side}">${r.best_side}</div>
    <div class="loc">on <b>${r.city} ${r.threshold_c}°</b> · ${r.date_str} · <span class="conf ${confClass(r.confidence)}">${r.confidence}</span></div>
    <div class="q">${esc(r.question)}</div>
    <div class="stats">
      <div class="stat"><div class="k">Our prediction</div><div class="v g">${win}%</div></div>
      <div class="stat"><div class="k">Market price</div><div class="v">${cents(price)}</div></div>
      <div class="stat"><div class="k">£10 → wins</div><div class="v g">£${wins}</div></div>
    </div>
    <a class="btn" href="${r.poly_url}" target="_blank">Back ${r.best_side} on Polymarket →</a>
  </div>`;
}

const confClass = c => ({ High: "hi", Medium: "med", Low: "lo" }[c] || "lo");

// live bet calculator: stake -> shares, payout, profit, expected value
function calcBet(input) {
  const stake = parseFloat(input.value) || 0;
  const price = parseFloat(input.dataset.price) || 0;   // market price of the side (0-1)
  const model = parseFloat(input.dataset.model) || 0;   // our win probability (0-1)
  const out = input.parentElement.querySelector(".calcout");
  if (!stake || !price) { out.innerHTML = ""; return; }
  const shares = stake / price;
  const payout = shares;               // each winning share pays £1
  const profit = payout - stake;
  const ev = model * payout - stake;   // expected profit using our prediction
  const evPos = ev >= 0;
  out.innerHTML =
    `<b>${shares.toFixed(1)}</b> shares · win pays <b>£${payout.toFixed(2)}</b> ` +
    `(profit <b class="pos-up">+£${profit.toFixed(2)}</b>) · ` +
    `expected value <b class="${evPos ? "pos-up" : "pos-down"}">${evPos ? "+" : ""}£${ev.toFixed(2)}</b>`;
}
window.calcBet = calcBet;

function pickCard(r) {
  const side = (r.best_side || "").toLowerCase();
  const model = Math.round((r.model_prob != null ? (side === "yes" ? r.model_prob : 1 - r.model_prob) : r.p_win) * 100);
  const pMkt = Math.round((r.p_market || 0) * 100);
  const gap = Math.abs(model - pMkt);
  const act = r.actionable ? `<span class="act-tag">✓ bettable now</span>` : `<span class="act-tag watch">watchlist</span>`;
  const stn = r.station_confirmed
    ? `<span class="station ok">✓ exact station</span>`
    : `<span class="station approx">~ approx location</span>`;
  return `<div class="pick">
    <div class="top">
      <div class="predict">
        <div class="pnum">${model}%</div>
        <div class="plbl">our prediction<br>${r.best_side} wins</div>
      </div>
      <div class="pmain">
        <div style="display:flex;align-items:center;gap:9px;flex-wrap:wrap">
          <span class="side ${side}">${r.best_side}</span>
          <span class="conf ${confClass(r.confidence)}">${r.confidence} confidence</span>
          ${act}
        </div>
        <div class="q">${esc(r.question)}</div>
        <div style="margin-top:6px">${stn}<span class="ens"> · ${r.members} sims (GFS+ECMWF) · ${r.lead_days}d out</span></div>
      </div>
      <div class="kelly"><div class="amt">$${r.bet_usd || "—"}</div><div class="lbl">¼-Kelly bet</div></div>
    </div>
    <div class="reason">${r.reasoning || ""}</div>
    <div class="gapbar">
      <div class="lbls"><span>Our prediction <b>${model}%</b></span><span>Market price <b>${pMkt}%</b></span></div>
      <div class="gaptrack"><div class="gapfill" style="width:${model}%"></div><div class="gapmark" style="left:${pMkt}%"></div></div>
      <div class="gap-note">Edge <b>${cents(r.edge)}</b> — we're ${gap} points more confident than the market</div>
    </div>
    <div class="wx">
      <span>needs <b>${r.threshold_c}°</b></span>
      <span>so far <b>${r.high_so_far_c ?? "—"}°</b></span>
      <span>volume <b>$${Number(r.volume_usd || 0).toLocaleString()}</b></span>
      <span><a class="mkt" href="${r.poly_url}" target="_blank">open market →</a></span>
    </div>
    <div class="calc">
      <span class="calclbl">💷 Stake £</span>
      <input class="calcin" type="number" value="1" min="0.1" step="0.5"
             data-price="${r.p_market}" data-model="${(model / 100).toFixed(3)}"
             oninput="calcBet(this)" onfocus="calcBet(this)">
      <span class="calcout"></span>
    </div>
    <button class="ai-btn" onclick="runAgent('${attr(r.question)}','prediction','${attr('Market prices yes ' + (r.yes_price || '?') + '. Our GFS ensemble model gives ' + model + '% for ' + r.best_side + '.')}', this)">🧠 Deeper AI research on this bet</button>
    <div class="ai-out"></div>
  </div>`;
}

async function loadPredictions() {
  $("#top-cards").innerHTML = `<div class="muted">pulling live markets + 82-member GFS+ECMWF ensemble…</div>`;
  const d = await get("/api/weather-edge");
  if (d.error) {
    $("#top-cards").innerHTML = $("#pick-cards").innerHTML = `<div class="muted">${esc(d.error)}</div>`;
    return;
  }
  const c = d.counts || {}, L = d.ledger || {}, cal = d.calibration || {};
  $("#picks-sub").textContent = `${c.actionable || 0} actionable · ${c.liquid || 0} liquid · ${c.total || 0} scanned`;
  const learnNote = cal.resolved
    ? `🧠 Self-learning: Brier ${cal.brier} (lower = sharper). ` +
      cal.buckets.map(b => `predicted ${b.predicted}% → won ${b.actual}%`).join(" · ")
    : (L.note || "");
  const pnl = L.net_pnl, roi = L.roi_pct;
  const pnlColor = pnl == null ? "" : (pnl >= 0 ? "color:#16a34a" : "color:#dc2626");
  const pnlStr = pnl == null ? "—" : (pnl >= 0 ? "+$" + pnl.toFixed(2) : "-$" + Math.abs(pnl).toFixed(2));
  $("#ledger-banner").innerHTML = `
    <div class="lstat"><div class="k">Net P&L (paper)</div><div class="v" style="${pnlColor}">${pnlStr}</div></div>
    <div class="lstat"><div class="k">ROI</div><div class="v" style="${pnlColor}">${roi != null ? (roi >= 0 ? "+" : "") + roi + "%" : "—"}</div></div>
    <div class="lstat"><div class="k">Resolved</div><div class="v">${L.resolved ?? 0}<span style="font-size:.6em;opacity:.6"> / ${L.logged ?? 0}</span></div></div>
    <div class="lstat"><div class="k">Win rate</div><div class="v">${L.win_rate != null ? L.win_rate + "%" : "—"}<span style="font-size:.55em;opacity:.6"> (low=OK)</span></div></div>
    <div class="lnote">${learnNote}</div>`;
  const picks = d.picks || [];
  const rateLimited = d.data_status === "rate_limited";
  const onFallback = d.data_status === "fallback";
  const emptyMsg = rateLimited
    ? `<div class="muted">⚠️ Weather forecast data is temporarily unavailable — the free weather API's daily request limit was hit. It resets tomorrow; the model can't score markets until then. (Not a "no edge" result — no data.)</div>`
    : `<div class="muted">No edges this scan — the model found no liquid market it disagrees with. Markets and forecasts move hourly; check back.</div>`;
  const fallbackBanner = onFallback
    ? `<div class="muted">⚙️ Running on backup weather sources (Met.no / NWS) — Open-Meteo is capped. Forecasts are single-source and coarser, so treat these as lower-confidence until it resets.</div>`
    : "";
  $("#top-cards").innerHTML = fallbackBanner + (picks.length
    ? picks.slice(0, 4).map((r, i) => topCard(r, i)).join("")
    : emptyMsg);
  renderCalendar(d.upcoming || []);
  $("#pick-cards").innerHTML = picks.map(pickCard).join("")
    || (rateLimited ? emptyMsg : `<div class="muted">Nothing to break down right now.</div>`);
  $$(".calcin").forEach(calcBet);  // show default £1 calc on every card
  loadWeekAhead();
}

async function loadWeekAhead() {
  const el = $("#week-ahead");
  try {
    const d = await get("/api/week-ahead");
    const dates = d.dates || [], rows = d.rows || [];
    if (!rows.length) { el.innerHTML = `<div class="muted">No market cities to forecast right now.</div>`; return; }
    const dayName = iso => new Date(iso + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" });
    const head = `<th style="text-align:left">City</th>` +
      dates.map((dt, i) => `<th>${i === 0 ? "Today" : dayName(dt)}<br><span class="muted" style="font-weight:400">${dt.slice(5)}</span></th>`).join("");
    const body = rows.map(r => {
      const cells = dates.map(dt => {
        const v = r.highs[dt];
        return `<td style="text-align:center">${v == null ? "—" : v + "°"}</td>`;
      }).join("");
      return `<tr><td>${r.city}</td>${cells}</tr>`;
    }).join("");
    el.innerHTML = `<div style="overflow-x:auto"><table class="wk"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    $("#week-sub").textContent = `${rows.length} market cities · free Met.no forecast`;
  } catch (e) {
    el.innerHTML = `<div class="muted">Couldn't load the week-ahead forecast.</div>`;
  }
}

async function loadLab() {
  const s = await get("/api/strategies");
  const rows = s.rows || [];
  barChart($("#lab-chart"), rows, "ret", v => v.toFixed(1) + "%",
           v => v >= 100 ? "var(--green)" : "var(--accent)");
  $("#lab-table tbody").innerHTML = rows.map(r =>
    `<tr><td>${r.name}</td><td>+${r.ret}%</td>
     <td class="pos-down">${r.dd}%</td><td>${(r.ret / Math.abs(r.dd)).toFixed(2)}</td></tr>`
  ).join("");
}

function marketCard(m) {
  const odds = (m.pairs || []).map(p => `<span class="oc">${p[0]} <b>${Math.round(p[1] * 100)}%</b></span>`).join("");
  return `<div class="mkt">
    <div class="mq"><a class="mkt" href="${m.url}" target="_blank" style="color:inherit;text-decoration:none">${esc(m.question)}</a></div>
    <div class="mmeta">${m.category ? `<span class="mcat">${esc(m.category)}</span>` : ""}
      <span>vol $${Number(m.volume).toLocaleString()}</span>${m.end ? `<span>ends ${m.end}</span>` : ""}</div>
    <div class="odds">${odds}</div>
    <button class="ai-btn" onclick="runAgent('${attr(m.question)}','prediction','${attr('Market odds: ' + (m.pairs || []).map(p => p[0] + ' ' + Math.round(p[1] * 100) + '%').join(', ') + '.')}', this)">🧠 Ask the AI analyst</button>
    <div class="ai-out"></div>
  </div>`;
}

let mktLoaded = false;
async function loadMarkets(force) {
  if (mktLoaded && !force) return;
  const cards = $("#mkt-cards");
  cards.className = "mkt-grid";
  cards.innerHTML = `<div class="muted">loading Polymarket…</div>`;
  const q = ($("#mkt-q").value || "").trim();
  const d = await get("/api/markets" + (q ? "?q=" + encodeURIComponent(q) : ""));
  if (d.error) { mktLoaded = false; cards.innerHTML = `<div class="muted">${esc(d.error)}</div>`; return; }
  mktLoaded = true;
  $("#mkt-sub").textContent = `${(d.rows || []).length} markets${q ? ' matching "' + q + '"' : ' (most active)'}`;
  cards.innerHTML = (d.rows || []).map(marketCard).join("") || `<div class="muted">no markets found</div>`;
}

// compact bet card for the calendar
function calCard(r) {
  const side = (r.best_side || "").toLowerCase();
  const win = Math.round((side === "yes" ? r.model_prob : 1 - r.model_prob) * 100);
  return `<a class="calcard" href="${r.poly_url}" target="_blank">
    <div class="calpct ${side}">${win}%</div>
    <div class="calbody">
      <div class="calside side ${side}">${r.best_side} · <span class="conf ${confClass(r.confidence)}">${r.confidence}</span></div>
      <div class="calloc">${r.city} ${r.threshold_c}°</div>
    </div>
    <div class="caledge">+${cents(r.edge)}</div>
  </a>`;
}

function dayLabel(lead, dateStr) {
  if (lead === 0) return "Today";
  if (lead === 1) return "Tomorrow";
  try {
    const d = new Date(dateStr + "T12:00:00");
    return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
  } catch { return dateStr; }
}

function renderCalendar(upcoming) {
  const up = (upcoming || []).filter(r => r.market_date);
  if (!up.length) { $("#cal-content").innerHTML = `<div class="muted">No upcoming bets.</div>`; $("#cal-sub").textContent = ""; return; }
  const byDate = {};
  up.forEach(r => { (byDate[r.market_date] ||= []).push(r); });
  const dates = Object.keys(byDate).sort();
  $("#cal-sub").textContent = `${up.length} bets across ${dates.length} days`;
  $("#cal-content").innerHTML = dates.map(dt => {
    const bets = byDate[dt].sort((a, b) => (b.edge || 0) - (a.edge || 0));
    const lead = bets[0].lead_days;
    return `<div class="calday">
      <div class="calhead"><span class="caldate">${dayLabel(lead, dt)}</span>
        <span class="muted">${dt} · ${bets.length} bet${bets.length > 1 ? "s" : ""}</span></div>
      <div class="calgrid">${bets.map(calCard).join("")}</div>
    </div>`;
  }).join("");
}

// AI research on world markets
function aiCard(r) {
  if (r.error) return `<div class="pick"><div class="q">${esc(r.question)}</div>
    <div class="muted">⚠ ${esc(r.error)}</div></div>`;
  const dir = (r.direction || "hold").toLowerCase();
  const conf = Math.round((r.confidence || 0) * 100);
  const mkt = r.market_prob != null ? Math.round(r.market_prob * 100) : null;
  const edgePts = r.edge != null ? Math.round(r.edge * 100) : null;
  const findings = (r.findings || []).map(f => `<li>${esc(f)}</li>`).join("");
  const odds = (r.pairs || []).map(p => `<span class="oc">${esc(p[0])} <b>${Math.round(p[1] * 100)}%</b></span>`).join(" ");
  return `<div class="pick">
    <div class="top">
      <div><span class="side ${dir === "no" || dir === "sell" ? "no" : dir === "hold" ? "" : "yes"}" style="font-size:24px">${(r.direction || "HOLD").toUpperCase()}</span>
        <span class="conf ${conf >= 60 ? "hi" : conf >= 40 ? "med" : "lo"}">${conf}% AI confidence</span></div>
      ${edgePts != null ? `<div class="kelly"><div class="amt ${edgePts > 0 ? "pos-up" : "pos-down"}">${edgePts > 0 ? "+" : ""}${edgePts}pt</div><div class="lbl">vs market</div></div>` : ""}
    </div>
    <div class="q">${esc(r.question)}</div>
    <div class="reason">${esc(r.rationale || "")}</div>
    ${findings ? `<ul class="ai-find">${findings}</ul>` : ""}
    <div class="wx"><span>market odds: ${odds}</span>${mkt != null ? `<span>AI ${conf}% vs market ${mkt}%</span>` : ""}
      <span><a class="mkt" href="${r.url}" target="_blank">open market →</a></span></div>
  </div>`;
}

let aiPolling = false;
async function loadAIPicks() {
  const d = await get("/api/ai-picks");
  const running = d.running, done = d.done || 0, total = d.total || 0;
  $("#ai-sub").textContent = running ? `researching… ${done}/${total} done` :
    (d.results || []).length ? `${d.results.length} markets researched` : "not run yet";
  $("#ai-run").textContent = running ? "🔍 Researching… (~1 min/market)" : "🔍 Run AI research now";
  $("#ai-run").disabled = running;
  const res = (d.results || []).slice().sort((a, b) => Math.abs(b.edge || 0) - Math.abs(a.edge || 0));
  $("#ai-cards").innerHTML = res.length ? res.map(aiCard).join("")
    : `<div class="muted">${running ? "reading news + web on each market…" : "Click ‘Run AI research’ — Claude will read live news on the top world markets (~1 min each)."}</div>`;
  if (running && !aiPolling) { aiPolling = true; setTimeout(pollAI, 4000); }
}
async function pollAI() {
  await loadAIPicks();
  const d = await get("/api/ai-picks");
  if (d.running) setTimeout(pollAI, 4000); else aiPolling = false;
}

const LOADERS = {overview: loadOverview, trades: loadTrades, stocks: loadStocks, predictions: loadPredictions, aipicks: loadAIPicks, markets: () => loadMarkets(false), lab: loadLab};
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
$("#ai-run").onclick = async () => { await get("/api/ai-picks?run=1"); loadAIPicks(); };

// initial load + auto-refresh the active view every 30s
show("overview");
setInterval(() => show(current), 30000);
