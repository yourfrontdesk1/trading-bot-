"""Local web dashboard for the trading bot. Runs on http://localhost:8080

Shows, live in your browser:
  - Alpaca paper account balance + open positions
  - Current strategy signals for the watchlist
  - Polymarket long-shot scan
  - The 5-strategy backtest verdict

No external services. Pure Python stdlib + the clients we already built.
Run:  python dashboard.py   then open http://localhost:8080
"""
import json
import html
from http.server import BaseHTTPRequestHandler, HTTPServer

import config
from brokers.polymarket_client import PolymarketClient
from strategies.momentum import Params, signal

PORT = 8080
WATCHLIST = ["AAPL", "MSFT", "SPY", "NVDA", "AMD", "TSM"]

# static learning result from strategy_lab.py (SPY 2018-2025)
LAB = [
    ("Buy & Hold", 122.5, -34.2), ("Monthly DCA", 61.9, -18.4),
    ("200-day Trend", 58.8, -20.8), ("RSI Mean-Reversion", 49.8, -28.8),
    ("SMA Crossover", 43.2, -29.6),
]


def alpaca_block():
    try:
        from brokers.alpaca_client import AlpacaClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from datetime import datetime, timedelta
        a = AlpacaClient()
        equity = a.account_value()
        positions = a.trading.get_all_positions()
        mode = "PAPER" if config.ALPACA_PAPER else "LIVE"
        rows = []
        for sym in WATCHLIST:
            try:
                end = datetime.now(); start = end - timedelta(days=400)
                bars = a.data.get_stock_bars(StockBarsRequest(
                    symbol_or_symbols=sym, timeframe=TimeFrame.Day, start=start
                )).data.get(sym, [])
                closes = [b.close for b in bars]
                sig = signal(closes, Params()) if closes else "?"
                price = closes[-1] if closes else 0
                rows.append((sym, price, sig))
            except Exception:
                rows.append((sym, 0, "?"))
        return mode, equity, positions, rows
    except Exception as e:
        return "OFFLINE", 0, [], [("keys?", 0, str(e)[:40])]


def poly_block():
    try:
        p = PolymarketClient()
        markets = p.active_markets(limit=25)
        notes = []
        for m in markets:
            pairs = PolymarketClient.outcome_prices(m)
            if not pairs:
                continue
            outcome, prob = min(pairs, key=lambda op: op[1])
            if prob < 0.10:
                notes.append((m.get("question", "?")[:70], outcome, prob))
        return notes[:12]
    except Exception as e:
        return [("error", str(e)[:40], 0)]


def render():
    mode, equity, positions, sig_rows = alpaca_block()
    poly = poly_block()

    def sig_color(s):
        return {"buy": "#22c55e", "sell": "#ef4444"}.get(s, "#94a3b8")

    sig_html = "".join(
        f"<tr><td>{html.escape(s)}</td><td>${p:,.2f}</td>"
        f"<td style='color:{sig_color(sg)};font-weight:600'>{sg.upper()}</td></tr>"
        for s, p, sg in sig_rows
    )
    pos_html = "".join(
        f"<tr><td>{html.escape(str(pp.symbol))}</td><td>{pp.qty}</td>"
        f"<td>${float(pp.market_value):,.2f}</td></tr>" for pp in positions
    ) or "<tr><td colspan=3 style='color:#64748b'>no open positions</td></tr>"
    poly_html = "".join(
        f"<tr><td>{html.escape(q)}</td><td>{html.escape(o)}</td>"
        f"<td>{pr:.2f}</td></tr>" for q, o, pr in poly
    )
    lab_html = "".join(
        f"<tr><td>{html.escape(n)}</td><td>{r:+.1f}%</td>"
        f"<td style='color:#f59e0b'>{d:.1f}%</td></tr>" for n, r, d in LAB
    )
    dry = "ON (nothing placed)" if config.DRY_RUN else "OFF (placing trades)"

    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta http-equiv=refresh content=30>
<title>Trading Bot</title>
<style>
body{{background:#0f172a;color:#e2e8f0;font:14px/1.5 -apple-system,system-ui,sans-serif;margin:0;padding:24px}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:14px;color:#94a3b8;margin:24px 0 8px;text-transform:uppercase;letter-spacing:.05em}}
.bar{{display:flex;gap:24px;flex-wrap:wrap;margin:12px 0}}
.card{{background:#1e293b;border-radius:10px;padding:16px 20px}}
.big{{font-size:26px;font-weight:700}} .muted{{color:#64748b;font-size:12px}}
table{{width:100%;border-collapse:collapse;background:#1e293b;border-radius:10px;overflow:hidden}}
td,th{{padding:8px 14px;text-align:left;border-bottom:1px solid #334155}} th{{color:#94a3b8;font-weight:600}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:24px}} @media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>🤖 Trading Bot</h1><div class=muted>auto-refreshes every 30s</div>
<div class=bar>
  <div class=card><div class=muted>{mode} EQUITY</div><div class=big>${equity:,.0f}</div></div>
  <div class=card><div class=muted>DRY RUN</div><div class=big style='font-size:16px'>{dry}</div></div>
  <div class=card><div class=muted>OPEN POSITIONS</div><div class=big>{len(positions)}</div></div>
</div>
<div class=grid>
<div><h2>Stock signals</h2><table><tr><th>Symbol</th><th>Price</th><th>Signal</th></tr>{sig_html}</table>
<h2>Open positions</h2><table><tr><th>Symbol</th><th>Qty</th><th>Value</th></tr>{pos_html}</table></div>
<div><h2>Polymarket long-shots (&lt;0.10)</h2><table><tr><th>Market</th><th>Outcome</th><th>Prob</th></tr>{poly_html}</table></div>
</div>
<h2>What the backtest taught us (SPY 2018-2025)</h2>
<table><tr><th>Strategy</th><th>Return</th><th>Max drawdown</th></tr>{lab_html}</table>
<div class=muted style='margin-top:8px'>No timing strategy beat Buy &amp; Hold. Evidence, not opinion.</div>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_response(404); self.end_headers(); return
        body = render().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Dashboard live at http://localhost:{PORT}  (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
