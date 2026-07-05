"""Full trading-bot web app. Backend API + static frontend on one local server.

Endpoints (JSON):
  GET /api/overview     - account mode, equity, dry-run, position count
  GET /api/signals      - stock watchlist prices + strategy signals
  GET /api/positions    - open paper positions
  GET /api/polymarket   - prediction-market scan (long-shots + top by volume)
  GET /api/strategies   - the 5-strategy backtest results

Serves the SPA in static/. Run:  python webapp/server.py  -> http://localhost:8080
"""
import os
import sys
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

# allow importing the project root (brokers/, strategies/, config)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from brokers.polymarket_client import PolymarketClient
from strategies.momentum import Params, signal

PORT = 8080
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
WATCHLIST = ["AAPL", "MSFT", "SPY", "NVDA", "AMD", "TSM"]

STRATEGIES = [
    {"name": "Buy & Hold", "ret": 122.5, "dd": -34.2},
    {"name": "Monthly DCA", "ret": 61.9, "dd": -18.4},
    {"name": "200-day Trend", "ret": 58.8, "dd": -20.8},
    {"name": "RSI Mean-Reversion", "ret": 49.8, "dd": -28.8},
    {"name": "SMA Crossover", "ret": 43.2, "dd": -29.6},
]

_alp = None


def alpaca():
    global _alp
    if _alp is None:
        from brokers.alpaca_client import AlpacaClient
        _alp = AlpacaClient()
    return _alp


def api_overview():
    try:
        a = alpaca()
        return {
            "mode": "PAPER" if config.ALPACA_PAPER else "LIVE",
            "equity": round(a.account_value(), 2),
            "dry_run": config.DRY_RUN,
            "positions": len(a.trading.get_all_positions()),
            "online": True,
        }
    except Exception as e:
        return {"mode": "OFFLINE", "equity": 0, "dry_run": config.DRY_RUN,
                "positions": 0, "online": False, "error": str(e)[:80]}


def api_signals():
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from datetime import datetime, timedelta
    out = []
    try:
        a = alpaca()
        for sym in WATCHLIST:
            try:
                start = datetime.now() - timedelta(days=400)
                bars = a.data.get_stock_bars(StockBarsRequest(
                    symbol_or_symbols=sym, timeframe=TimeFrame.Day, start=start
                )).data.get(sym, [])
                closes = [b.close for b in bars]
                out.append({"symbol": sym,
                            "price": round(closes[-1], 2) if closes else 0,
                            "signal": signal(closes, Params()) if closes else "?"})
            except Exception:
                out.append({"symbol": sym, "price": 0, "signal": "?"})
    except Exception as e:
        return {"error": str(e)[:80], "rows": []}
    return {"rows": out}


def api_positions():
    try:
        a = alpaca()
        return {"rows": [
            {"symbol": p.symbol, "qty": p.qty,
             "value": round(float(p.market_value), 2),
             "pl": round(float(p.unrealized_pl), 2)}
            for p in a.trading.get_all_positions()]}
    except Exception as e:
        return {"error": str(e)[:80], "rows": []}


def api_polymarket():
    try:
        p = PolymarketClient()
        markets = p.active_markets(limit=30)
        longshots, top = [], []
        for m in markets:
            pairs = PolymarketClient.outcome_prices(m)
            if not pairs:
                continue
            q = (m.get("question") or "?")[:90]
            vol = float(m.get("volume") or 0)
            top.append({"q": q, "vol": round(vol), "pairs": pairs[:2]})
            outcome, prob = min(pairs, key=lambda op: op[1])
            if prob < 0.10:
                longshots.append({"q": q, "outcome": outcome, "prob": round(prob, 3)})
        top.sort(key=lambda x: x["vol"], reverse=True)
        return {"longshots": longshots[:12], "top": top[:10]}
    except Exception as e:
        return {"error": str(e)[:80], "longshots": [], "top": []}


def api_strategies():
    return {"rows": STRATEGIES}


ROUTES = {
    "/api/overview": api_overview,
    "/api/signals": api_signals,
    "/api/positions": api_positions,
    "/api/polymarket": api_polymarket,
    "/api/strategies": api_strategies,
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ROUTES:
            try:
                data = ROUTES[path]()
            except Exception as e:
                data = {"error": str(e)[:120]}
            return self._send(200, json.dumps(data), "application/json")
        # static files
        if path == "/":
            path = "/index.html"
        fp = os.path.join(STATIC, path.lstrip("/"))
        if os.path.isfile(fp):
            ctype = ("text/html" if fp.endswith(".html")
                     else "application/javascript" if fp.endswith(".js")
                     else "text/css" if fp.endswith(".css") else "text/plain")
            with open(fp, "rb") as f:
                return self._send(200, f.read(), ctype + "; charset=utf-8")
        self._send(404, "not found", "text/plain")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Trading Bot app live at http://localhost:{PORT}  (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
