"""Self-contained weather-edge engine for the trading bot.

Ports Leon's proven polybot algorithm (parse temp market -> join Open-Meteo
forecast -> compute edge -> quarter-Kelly size) into one standalone module that
pulls everything LIVE, so it doesn't depend on the polybot backend/db.

Credit: logic mirrors ~/polymarket-bot/backend/weather_edge.py + tools/weather.py.
"""
import re
import json
import time
from datetime import datetime, date

import requests

GAMMA = "https://gamma-api.polymarket.com"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
FEE_PER_SHARE = 0.02
BANKROLL_USD = 200.0     # matches polybot MAX_POSITION_USD scale
TRADE_CAP_USD = 50.0

PATTERN = re.compile(
    r"(?P<kind>highest|lowest) temperature in (?P<city>[\w\s]+?) be (?P<threshold>\d+)\s*°?[CF]"
    r"(?P<modifier>\s+or higher|\s+or below)? on (?P<date>[\w\s\d]+?)\??$",
    re.IGNORECASE,
)
MONTHS = {m: i for i, m in enumerate(
    ["january","february","march","april","may","june","july","august",
     "september","october","november","december"], 1)}

CITY_COORDS = {
    "Hong Kong": (22.32, 114.17), "London": (51.51, -0.13), "Paris": (48.86, 2.35),
    "New York City": (40.71, -74.01), "Miami": (25.76, -80.19), "Jinan": (36.65, 117.00),
    "Zhengzhou": (34.75, 113.62), "Seoul": (37.57, 126.98), "Tokyo": (35.68, 139.69),
    "Shanghai": (31.23, 121.47), "Sao Paulo": (-23.55, -46.63), "Buenos Aires": (-34.61, -58.38),
    "Toronto": (43.65, -79.38), "Seattle": (47.61, -122.33), "Dallas": (32.78, -96.80),
    "Atlanta": (33.75, -84.39), "Chicago": (41.88, -87.63), "Ankara": (39.93, 32.86),
    "Lucknow": (26.85, 80.95), "Tel Aviv": (32.08, 34.78), "Milan": (45.46, 9.19),
    "Madrid": (40.42, -3.70), "Warsaw": (52.23, 21.01), "Taipei": (25.03, 121.57),
    "Chongqing": (29.56, 106.55), "Wuhan": (30.59, 114.31), "Chengdu": (30.57, 104.07),
    "Shenzhen": (22.54, 114.06), "Austin": (30.27, -97.74), "Houston": (29.76, -95.37),
    "Los Angeles": (34.05, -118.24), "San Francisco": (37.77, -122.42), "Moscow": (55.76, 37.62),
    "Istanbul": (41.01, 28.98), "Mexico City": (19.43, -99.13), "Amsterdam": (52.37, 4.90),
    "Helsinki": (60.17, 24.94), "Jeddah": (21.49, 39.19), "Qingdao": (36.07, 120.38),
    "Karachi": (24.86, 67.01),
}

P_YES = {"LOCKED_YES": 0.98, "STRONG_YES": 0.80, "LEAN_YES": 0.55, "NEUTRAL": 0.30,
         "LEAN_NO": 0.15, "STRONG_NO": 0.05, "LOCKED_NO": 0.01, "STALE": None}

_wx_cache, _wx_ts = {}, 0.0


# ---------- parsing / edge (ported from polybot) ----------
def parse_date(date_str, fallback_year):
    parts = date_str.strip().split()
    if len(parts) < 2:
        return None
    mon = MONTHS.get(parts[0].lower())
    if not mon:
        return None
    try:
        return f"{fallback_year:04d}-{mon:02d}-{int(parts[1]):02d}"
    except Exception:
        return None


def parse_question(q):
    m = PATTERN.search(q.strip())
    if not m:
        return None
    modifier = (m.group("modifier") or "").strip().lower()
    return {"kind": m.group("kind").lower(), "city": m.group("city").strip(),
            "threshold_c": int(m.group("threshold")),
            "or_higher": modifier == "or higher", "or_below": modifier == "or below",
            "date_str": m.group("date").strip()}


def compute_edge(parsed, wx):
    threshold, or_higher, or_below = parsed["threshold_c"], parsed["or_higher"], parsed["or_below"]
    is_low = parsed.get("kind") == "lowest"
    so_far = wx.get("low_so_far_c") if is_low else wx.get("high_so_far_c")
    today_fc = wx.get("today_forecast_low_c") if is_low else wx.get("today_forecast_high_c")
    tomorrow_fc = wx.get("tomorrow_forecast_low_c") if is_low else wx.get("tomorrow_forecast_high_c")
    by_date = (wx.get("lows_by_date") if is_low else wx.get("highs_by_date")) or {}
    city_today = (wx.get("local_time", "") or "").split("T")[0] or None
    city_tomorrow = wx.get("tomorrow_date")
    fallback_year = int(city_today.split("-")[0]) if city_today else datetime.utcnow().year
    market_date = parse_date(parsed["date_str"], fallback_year)
    if market_date and city_today and market_date < city_today:
        return {"signal": "STALE", "delta_c": None, "market_date": market_date}
    is_today = market_date == city_today
    is_tomorrow = market_date == city_tomorrow
    fc = by_date.get(market_date) if market_date else None
    if fc is None and is_today: fc = today_fc
    if fc is None and is_tomorrow: fc = tomorrow_fc
    try:
        d_today = date.fromisoformat(city_today) if city_today else None
        d_market = date.fromisoformat(market_date) if market_date else None
        days_out = (d_market - d_today).days if d_today and d_market else None
    except Exception:
        days_out = None
    if fc is None:
        return {"signal": "NO_DATA", "delta_c": None, "market_date": market_date, "days_out": days_out}
    if is_today and not is_low and so_far is not None:
        if or_higher and so_far >= threshold:
            return {"signal": "LOCKED_YES", "delta_c": round(so_far - threshold, 1), "market_date": market_date, "days_out": days_out}
        if or_below and so_far > (threshold + 0.99):
            return {"signal": "LOCKED_NO", "delta_c": round(so_far - threshold, 1), "market_date": market_date, "days_out": days_out}
        if not or_higher and not or_below and so_far >= (threshold + 1):
            return {"signal": "LOCKED_NO", "delta_c": round(so_far - threshold, 1), "market_date": market_date, "days_out": days_out}
    delta = round(fc - threshold, 1)
    if or_higher:
        sig = ("STRONG_YES" if delta >= 3 else "LEAN_YES" if delta >= 1 else
               "STRONG_NO" if delta <= -3 else "LEAN_NO" if delta <= -1 else "NEUTRAL")
    elif or_below:
        sig = ("STRONG_YES" if delta <= -3 else "LEAN_YES" if delta <= -1 else
               "STRONG_NO" if delta >= 3 else "LEAN_NO" if delta >= 1 else "NEUTRAL")
    else:
        sig = ("LEAN_YES" if 0 <= delta <= 0.99 else "NEUTRAL" if abs(delta) <= 1.5 else
               "STRONG_NO" if abs(delta) >= 3 else "LEAN_NO")
    return {"signal": sig, "delta_c": delta, "market_date": market_date, "days_out": days_out}


def _decay(p, days_out):
    if days_out is None or days_out <= 1:
        return p
    return 0.5 + (p - 0.5) * (1 - min(0.6, 0.10 * (days_out - 1)))


def price_edge(signal, yes_price, no_price, days_out=None):
    if yes_price is None or no_price is None or signal in ("STALE", "NO_DATA"):
        return {"best_side": None, "edge": None, "p_win": None, "p_market": None}
    p = P_YES.get(signal)
    if p is None:
        return {"best_side": None, "edge": None, "p_win": None, "p_market": None}
    p = _decay(p, days_out)
    edge_yes = p - yes_price - FEE_PER_SHARE
    edge_no = (1 - p) - no_price - FEE_PER_SHARE
    if edge_yes >= edge_no:
        return {"best_side": "YES", "edge": round(edge_yes, 3), "p_win": round(p, 3), "p_market": round(yes_price, 3)}
    return {"best_side": "NO", "edge": round(edge_no, 3), "p_win": round(1 - p, 3), "p_market": round(no_price, 3)}


def bet_size_usd(edge, side_price, bankroll=BANKROLL_USD, cap=TRADE_CAP_USD):
    if not edge or edge <= 0 or not side_price or side_price <= 0 or side_price >= 1:
        return 0.0
    return round(min(bankroll * max(0, (edge / (1 - side_price)) * 0.25), cap), 2)


# ---------- live data ----------
def fetch_weather(cities):
    """Sync Open-Meteo fetch for the given city names. 1h cache."""
    global _wx_cache, _wx_ts
    if _wx_cache and time.time() - _wx_ts < 3600:
        return _wx_cache
    out = {}
    for city in cities:
        coords = CITY_COORDS.get(city)
        if not coords:
            continue
        try:
            r = requests.get(OPEN_METEO, params={
                "latitude": coords[0], "longitude": coords[1],
                "current": "temperature_2m", "hourly": "temperature_2m",
                "daily": "temperature_2m_max,temperature_2m_min",
                "timezone": "auto", "forecast_days": 16},
                headers={"User-Agent": "tradingbot/0.1"}, timeout=15)
            r.raise_for_status()
            d = r.json()
            cur = d.get("current", {})
            ctime = cur.get("time", "")
            tday = ctime.split("T")[0] if ctime else ""
            h = d.get("hourly", {})
            today_temps = [t for ti, t in zip(h.get("time", []), h.get("temperature_2m", []))
                           if ti.startswith(tday) and ti <= ctime and t is not None]
            dl = d.get("daily", {})
            highs, lows, dates = (dl.get("temperature_2m_max", []),
                                  dl.get("temperature_2m_min", []), dl.get("time", []))
            out[city] = {
                "current_temp_c": cur.get("temperature_2m"),
                "high_so_far_c": max(today_temps) if today_temps else None,
                "low_so_far_c": min(today_temps) if today_temps else None,
                "today_forecast_high_c": highs[0] if highs else None,
                "today_forecast_low_c": lows[0] if lows else None,
                "tomorrow_forecast_high_c": highs[1] if len(highs) > 1 else None,
                "tomorrow_forecast_low_c": lows[1] if len(lows) > 1 else None,
                "today_date": dates[0] if dates else None,
                "tomorrow_date": dates[1] if len(dates) > 1 else None,
                "highs_by_date": dict(zip(dates, highs)),
                "lows_by_date": dict(zip(dates, lows)),
                "local_time": ctime,
            }
        except Exception:
            continue
    _wx_cache, _wx_ts = out, time.time()
    return out


def _prices(market):
    outcomes, prices = market.get("outcomes"), market.get("outcomePrices")
    if isinstance(outcomes, str): outcomes = json.loads(outcomes)
    if isinstance(prices, str): prices = json.loads(prices)
    if not outcomes or not prices:
        return None, None
    d = {o.lower(): float(p) for o, p in zip(outcomes, prices)}
    return d.get("yes"), d.get("no")


def fetch_temp_markets(max_pages=6, page=200):
    """Page through active Polymarket markets, keep temperature ones."""
    keep = []
    for i in range(max_pages):
        r = requests.get(f"{GAMMA}/markets", params={
            "active": "true", "closed": "false", "limit": page, "offset": i * page,
            "order": "volume", "ascending": "false"}, timeout=20)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        for m in batch:
            q = m.get("question") or ""
            if "temperature" in q.lower() and parse_question(q):
                keep.append(m)
    return keep


def build_edge_table():
    """Returns ranked list of live weather-edge bet opportunities."""
    markets = fetch_temp_markets()
    cities = {parse_question(m["question"])["city"] for m in markets
              if parse_question(m.get("question", ""))}
    cities = {c for c in cities if c in CITY_COORDS}
    wx_all = fetch_weather(cities)

    rows = []
    for m in markets:
        parsed = parse_question(m["question"])
        wx = wx_all.get(parsed["city"])
        if not wx:
            continue
        yes_p, no_p = _prices(m)
        edge = compute_edge(parsed, wx)
        pe = price_edge(edge["signal"], yes_p, no_p, days_out=edge.get("days_out"))
        side_price = (yes_p if pe["best_side"] == "YES" else no_p) or 0
        bet = bet_size_usd(pe["edge"], side_price)
        ev = m.get("events")
        slug = (ev[0].get("slug") if isinstance(ev, list) and ev else None) or m.get("slug")
        is_low = parsed.get("kind") == "lowest"
        rows.append({
            "question": m["question"], "city": parsed["city"],
            "threshold_c": parsed["threshold_c"], "kind": parsed["kind"],
            "or_higher": parsed["or_higher"], "or_below": parsed["or_below"],
            "date_str": parsed["date_str"],
            "high_so_far_c": wx.get("low_so_far_c") if is_low else wx.get("high_so_far_c"),
            "today_forecast_c": wx.get("today_forecast_low_c") if is_low else wx.get("today_forecast_high_c"),
            "tomorrow_forecast_c": wx.get("tomorrow_forecast_low_c") if is_low else wx.get("tomorrow_forecast_high_c"),
            "yes_price": yes_p, "no_price": no_p,
            "volume_usd": round(float(m.get("volume") or 0)),
            "bet_usd": bet,
            "liquid": bool(yes_p and no_p and 0.05 <= yes_p <= 0.95 and 0.05 <= no_p <= 0.95),
            "poly_url": f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com",
            **edge, **pe,
        })
    rows.sort(key=lambda r: (r.get("edge") is None, -(r.get("edge") or -999)))
    return rows


if __name__ == "__main__":
    t = build_edge_table()
    print(f"{len(t)} temp markets with edge data")
    for r in t[:5]:
        print(f"  {r['best_side']} {r['city']} {r['threshold_c']}° "
              f"edge={r['edge']} win={r.get('p_win')} bet=${r['bet_usd']} :: {r['signal']}")
