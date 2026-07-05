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
from strategies.momentum import Params, signal, position_size

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
                spark = [round(c, 2) for c in closes[-60:]]
                change = round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) > 1 else 0
                sig = signal(closes, Params()) if closes else "?"
                price = closes[-1] if closes else 0
                sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
                sma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
                above200 = bool(sma200 and price > sma200)
                if sig == "buy":
                    why = "20d crossed above 50d in an uptrend"
                elif sig == "sell":
                    why = "20d crossed below 50d — trend broke"
                elif above200:
                    why = "above 200-day trend, waiting for a crossover"
                else:
                    why = "below 200-day trend — stay out"
                # trade plan: risk-managed position sizing (1% equity risk, 8% stop)
                p = Params()
                try:
                    equity = alpaca().account_value()
                except Exception:
                    equity = 100000
                qty = position_size(equity, price, p)
                stop_price = round(price * (1 - p.stop_pct), 2)
                dollars = round(qty * price, 2)
                risk_dollars = round(qty * price * p.stop_pct, 2)
                out.append({"symbol": sym, "price": round(price, 2), "change": change,
                            "spark": spark, "signal": sig, "why": why,
                            "above200": above200,
                            "sma50": round(sma50, 2) if sma50 else None,
                            "sma200": round(sma200, 2) if sma200 else None,
                            "plan": {"qty": qty, "dollars": dollars, "stop": stop_price,
                                     "risk": risk_dollars, "stop_pct": int(p.stop_pct * 100)}})
            except Exception:
                out.append({"symbol": sym, "price": 0, "change": 0, "spark": [],
                            "signal": "?", "why": "", "above200": False})
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


def _poly_url(m):
    ev = m.get("events")
    slug = None
    if isinstance(ev, list) and ev:
        slug = ev[0].get("slug")
    slug = slug or m.get("slug")
    return f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"


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
            url = _poly_url(m)
            vol = float(m.get("volume") or 0)
            top.append({"q": q, "vol": round(vol), "pairs": pairs[:2], "url": url})
            outcome, prob = min(pairs, key=lambda op: op[1])
            if prob < 0.10:
                longshots.append({"q": q, "outcome": outcome, "prob": round(prob, 3), "url": url})
        top.sort(key=lambda x: x["vol"], reverse=True)
        return {"longshots": longshots[:12], "top": top[:10]}
    except Exception as e:
        return {"error": str(e)[:80], "longshots": [], "top": []}


def api_trades():
    """Real trades from the Alpaca account: open positions (with entry price/time)
    and recent orders (with status). This mirrors exactly what IS being traded."""
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        a = alpaca()
        positions = []
        for p in a.trading.get_all_positions():
            positions.append({
                "symbol": p.symbol, "qty": p.qty,
                "entry": round(float(p.avg_entry_price), 2),
                "price": round(float(p.current_price), 2),
                "value": round(float(p.market_value), 2),
                "pl": round(float(p.unrealized_pl), 2),
                "pl_pct": round(float(p.unrealized_plpc) * 100, 2),
            })
        orders = []
        try:
            req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=25)
            for o in a.trading.get_orders(req):
                orders.append({
                    "symbol": o.symbol, "side": str(o.side).split(".")[-1].lower(),
                    "qty": str(o.qty), "status": str(o.status).split(".")[-1].lower(),
                    "submitted": str(o.submitted_at)[:19] if o.submitted_at else "",
                    "filled_price": round(float(o.filled_avg_price), 2) if o.filled_avg_price else None,
                })
        except Exception:
            pass
        return {"positions": positions, "orders": orders,
                "dry_run": config.DRY_RUN, "count": len(positions) + len(orders)}
    except Exception as e:
        return {"error": str(e)[:100], "positions": [], "orders": []}


def api_strategies():
    return {"rows": STRATEGIES}


def api_agent(query):
    """On-demand AI analyst. query: {subject, kind, context}. Slow (web search)."""
    from urllib.parse import parse_qs
    q = parse_qs(query)
    subject = (q.get("subject", [""])[0]).strip()
    kind = (q.get("kind", ["stock"])[0]).strip()
    context = (q.get("context", [""])[0]).strip()
    if not subject:
        return {"error": "no subject"}
    try:
        from strategies.agent import analyze
        return analyze(subject, kind, context)
    except Exception as e:
        return {"error": str(e)[:150]}


def api_weather_edge():
    """Live weather-edge bet opportunities, ranked. Mirrors the polybot approach."""
    try:
        from strategies.weather_edge import build_edge_table
        rows = build_edge_table()
        actionable = [r for r in rows if r.get("edge") and r["edge"] > 0 and r.get("bet_usd", 0) > 0]
        top = [r for r in actionable if (r.get("p_win") or 0) >= 0.90][:3]
        return {"top": top, "picks": actionable[:20],
                "counts": {"top": len(top), "liquid": sum(1 for r in rows if r.get("liquid")),
                           "total": len(rows)}}
    except Exception as e:
        return {"error": str(e)[:120], "top": [], "picks": [], "counts": {}}


ROUTES = {
    "/api/overview": api_overview,
    "/api/signals": api_signals,
    "/api/positions": api_positions,
    "/api/polymarket": api_polymarket,
    "/api/strategies": api_strategies,
    "/api/trades": api_trades,
    "/api/weather-edge": api_weather_edge,
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
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        if path == "/api/agent":
            data = api_agent(query)
            return self._send(200, json.dumps(data), "application/json")
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
