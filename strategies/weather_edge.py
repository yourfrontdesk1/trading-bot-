"""Weather-edge engine v2 — the one strategy that actually fits a £30 / £1-bet
bankroll, rebuilt from the 15-agent research to be as sharp as possible.

Upgrades over v1:
  1. REAL money numbers: £38 bankroll, ~$2 cap (v1 lied with $200/$50).
  2. ENSEMBLE probability: 82-member GFS+ECMWF ensemble blend -> P(bucket) = fraction of
     members landing in the bucket. A real distribution, not a hand-tuned ladder.
  3. RESOLUTION stations: markets settle on a specific airport METAR, not the
     city centre. We use the station coord where known and flag the rest.
  4. DYNAMIC maker/taker fee: maker orders are ~free; takers pay and it eats the
     whole edge. Edge is computed for MAKER execution.
  5. TIGHT selection: only fire when model beats price by a threshold, skip the
     0.40-0.60 fee/liquidity dead-zone, prefer cheap tails a £1 maker can rest in.

Credit: algorithm descends from Leon's polybot + suislanchez ensemble idea.
Still NOT a money printer — the goal is proving positive CLV before scaling.
"""
import re
import json
import time
import math
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor

import requests

GAMMA = "https://gamma-api.polymarket.com"
FORECAST_API = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_API = "https://ensemble-api.open-meteo.com/v1/ensemble"

# --- real bankroll for a £30 stake (~$38), £1 (~$1.25) bets ---
BANKROLL_USD = 38.0
TRADE_CAP_USD = 2.0
KELLY_FRACTION = 0.25          # quarter-Kelly
EDGE_THRESHOLD = 0.08          # only trade if model_prob - price > this
EDGE_SANITY_CAP = 0.35         # edges above this = stale/illiquid price, not a real edge
VOLUME_FLOOR = 250             # need a real two-sided book to actually fill
MAKER_FEE = 0.0                # resting limit orders are fee-free on Polymarket
TAKER_FEE_RATE = 0.02          # market orders cost ~feeRate * min(p,1-p); we avoid these
MIN_SHARES = 5                 # Polymarket minimum order size
MAX_LEAD_DAYS = 3              # forecasts past ~3 days are too noisy to trust
MAX_EXPOSURE = 0.6             # never risk more than 60% of bankroll at once
ENSEMBLE_MODELS = "gfs025,ecmwf_ifs025"  # blend GFS (31) + ECMWF (51) = 82 members
MEMBER_SIGMA = 0.6          # per-member forecast uncertainty (°). TUNED from a 90-day
                            # historical backtest (backtest_weather.py): 0.6 minimises the
                            # Brier score — the forecasts are far more accurate than the
                            # 1.5 we first guessed. Widens each member into a smooth curve
                            # so a threshold far off is ~0% and one on-target is well-calibrated.

PATTERN = re.compile(
    r"(?P<kind>highest|lowest) temperature in (?P<city>[\w\s]+?) be (?P<threshold>\d+)\s*°?(?P<unit>[CF])"
    r"(?P<modifier>\s+or higher|\s+or below)? on (?P<date>[\w\s\d]+?)\??$",
    re.IGNORECASE,
)
MONTHS = {m: i for i, m in enumerate(
    ["january","february","march","april","may","june","july","august",
     "september","october","november","december"], 1)}

# City-centre coords (fallback). Markets actually settle on a station METAR.
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

# Resolution STATION coords, where confidently known (airport METAR the market
# settles on). Trading these matches the settlement feed instead of city-centre.
# Cities not listed fall back to CITY_COORDS and are flagged station_confirmed=False.
# Only include stations verified against the market's settlement source. Anything
# uncertain is left out (falls back to city-centre, flagged station_confirmed=False)
# rather than claiming a confirmed station we're not sure of.
RESOLUTION_STATION = {
    "New York City": (40.78, -73.97),   # Central Park (KNYC) — NWS CLI source
}

_wx_cache, _wx_ts = {}, 0.0
_ens_cache, _ens_ts = {}, {}   # per-key timestamps (high/low fetched separately)


def _ometeo_unit(u):
    return "fahrenheit" if u == "F" else "celsius"


# ---------- parsing ----------
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
    # threshold is in the market's NATIVE unit (F for US cities, C elsewhere);
    # we fetch forecasts in that same unit so bucketing stays correct.
    return {"kind": m.group("kind").lower(), "city": m.group("city").strip(),
            "threshold_c": int(m.group("threshold")),  # value is in `unit`, not always C
            "unit": m.group("unit").upper(),
            "or_higher": modifier == "or higher", "or_below": modifier == "or below",
            "date_str": m.group("date").strip()}


def station_for(city):
    """Return (lat, lon, confirmed) — resolution station if known, else city centre."""
    if city in RESOLUTION_STATION:
        return (*RESOLUTION_STATION[city], True)
    if city in CITY_COORDS:
        return (*CITY_COORDS[city], False)
    return None


# ---------- weather (current obs + point forecast, for locked checks) ----------
# `units` maps city -> 'C'/'F' so we fetch each city's forecast in the same unit
# the market is quoted/settled in (US cities = F). This keeps bucketing correct.
def _fetch_weather_one(args):
    city, unit = args
    loc = station_for(city)
    if not loc:
        return city, None
    lat, lon, _ = loc
    try:
        r = requests.get(FORECAST_API, params={
            "latitude": lat, "longitude": lon, "current": "temperature_2m",
            "hourly": "temperature_2m", "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": "auto", "forecast_days": 16, "temperature_unit": _ometeo_unit(unit)},
            headers={"User-Agent": "tradingbot/0.2"}, timeout=15)
        r.raise_for_status()
        d = r.json()
        cur = d.get("current", {}); ctime = cur.get("time", "")
        tday = ctime.split("T")[0] if ctime else ""
        h = d.get("hourly", {})
        today_temps = [t for ti, t in zip(h.get("time", []), h.get("temperature_2m", []))
                       if ti.startswith(tday) and ti <= ctime and t is not None]
        dl = d.get("daily", {})
        return city, {
            "high_so_far_c": max(today_temps) if today_temps else None,
            "low_so_far_c": min(today_temps) if today_temps else None,
            "today_date": (dl.get("time") or [None])[0],
            "tomorrow_date": (dl.get("time") or [None, None])[1] if len(dl.get("time", [])) > 1 else None,
            "local_time": ctime,
        }
    except Exception:
        return city, None


def fetch_weather(units):
    global _wx_cache, _wx_ts
    if _wx_cache and time.time() - _wx_ts < 1800:
        return _wx_cache
    out = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for city, data in ex.map(_fetch_weather_one, list(units.items())):
            if data:
                out[city] = data
    _wx_cache, _wx_ts = out, time.time()
    return out


# ---------- ensemble (the real probability distribution) ----------
def fetch_ensemble(units, is_low=False):
    """Return {city: {date: [member temps]}} from the 82-member GFS+ECMWF blend,
    fetched in each city's native unit."""
    global _ens_cache, _ens_ts
    key = "low" if is_low else "high"
    cache = _ens_cache.get(key)
    if cache and time.time() - _ens_ts.get(key, 0) < 1800:
        return cache
    var = "temperature_2m_min" if is_low else "temperature_2m_max"

    def one(args):
        city, unit = args
        loc = station_for(city)
        if not loc:
            return city, None
        lat, lon, _ = loc
        try:
            r = requests.get(ENSEMBLE_API, params={
                "latitude": lat, "longitude": lon, "daily": var,
                "models": ENSEMBLE_MODELS, "forecast_days": 7, "timezone": "auto",
                "temperature_unit": _ometeo_unit(unit)},
                headers={"User-Agent": "tradingbot/0.2"}, timeout=25)
            r.raise_for_status()
            d = r.json().get("daily", {})
            dates = d.get("time", [])
            member_keys = [k for k in d if k.startswith(var)]
            by_date = {}
            for i, dt in enumerate(dates):
                vals = [d[k][i] for k in member_keys if d[k] and d[k][i] is not None]
                if vals:
                    by_date[dt] = vals
            return city, by_date
        except Exception:
            return city, None

    out = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for city, data in ex.map(one, list(units.items())):
            if data is not None:
                out[city] = data
    _ens_cache[key] = out
    _ens_ts[key] = time.time()
    return out


def bucket_hits(members, parsed):
    """How many ensemble members land in the YES outcome."""
    T = parsed["threshold_c"]
    if parsed["or_higher"]:
        return sum(1 for m in members if m >= T)
    if parsed["or_below"]:
        return sum(1 for m in members if m <= T + 0.99)
    return sum(1 for m in members if T <= m < T + 1)  # exact 1-degree bucket


def _cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def bucket_probability(members, parsed):
    """P(YES) as a proper probabilistic forecast.

    Rather than counting hard hits (which makes a threshold just outside every
    member read as 0, then needs crude 'calibration'), we treat each of the 82
    members as the centre of a Normal(mean=member, sd=MEMBER_SIGMA) — i.e. 'about
    27°, give or take 1.5°'. P(YES) = the average over all members of the chance
    that member's true temperature satisfies the market's condition.

    This captures BOTH sources of uncertainty: disagreement between simulations
    (the spread) AND each simulation's own forecast error (MEMBER_SIGMA). A
    threshold far from every member comes out genuinely ~0; one inside the spread
    gets a smooth, well-calibrated probability. No arbitrary shrink needed.
    """
    if not members:
        return None
    T = parsed["threshold_c"]
    s = MEMBER_SIGMA

    def p_member(mv):
        if parsed["or_higher"]:          # true temp >= T
            return 1 - _cdf((T - mv) / s)
        if parsed["or_below"]:           # true temp <= T + 0.99
            return _cdf((T + 0.99 - mv) / s)
        return _cdf((T + 1 - mv) / s) - _cdf((T - mv) / s)  # exact bucket [T, T+1)

    p = sum(p_member(mv) for mv in members) / len(members)
    return min(0.97, max(0.005, p))


def build_reasoning(parsed, members, p_yes, pe, lead, station_ok):
    """Per-bet research summary, educated guess, and confidence — the plain-English
    'here's what I think and how sure I am' for each card."""
    n = len(members) if members else 0
    hits = bucket_hits(members, parsed) if members else 0
    side = pe["best_side"]
    model_pct = round((p_yes if side == "YES" else 1 - p_yes) * 100)
    mkt_pct = round((pe["p_market"] or 0) * 100)
    edge_pts = round((pe["edge"] or 0) * 100)
    kind = "at or above" if parsed["or_higher"] else "at or below" if parsed["or_below"] else "exactly at"
    yes_desc = (f"{hits} of {n} forecast simulations (GFS + ECMWF ensembles) land "
                f"{kind} {parsed['threshold_c']}°C")

    if side == "YES":
        call = f"the temperature WILL hit the target, so back YES"
    else:
        call = f"the temperature will MISS the target, so back NO"

    lead_note = ("today's market — the forecast is about as certain as it gets" if lead == 0
                 else "tomorrow — still a high-confidence forecast" if lead == 1
                 else f"{lead} days out, so the forecast carries more uncertainty")
    stn_note = ("scored against the exact station this market settles on"
                if station_ok else "scored against the city (settlement station not yet verified — small extra risk)")

    reasoning = (f"{yes_desc}, so our model puts the real chance at {model_pct}% while the "
                 f"market is pricing {mkt_pct}%. That {edge_pts}-point gap is the edge — {call}. "
                 f"It's {lead_note}, {stn_note}.")

    # confidence: bigger edge + confirmed station + near-term = higher
    score = edge_pts + (8 if station_ok else 0) + (6 if (lead or 9) <= 1 else 0)
    if score >= 22:
        conf = "High"
    elif score >= 14:
        conf = "Medium"
    else:
        conf = "Low"
    return {"reasoning": reasoning, "confidence": conf, "conf_model_pct": model_pct}


# ---------- pricing / sizing ----------
def price_edge(p_yes, yes_price, no_price, maker=True):
    """Best side + edge, computed for MAKER execution (fee ~0)."""
    if p_yes is None or yes_price is None or no_price is None:
        return {"best_side": None, "edge": None, "p_win": None, "p_market": None}
    fee = MAKER_FEE if maker else TAKER_FEE_RATE
    edge_yes = p_yes - yes_price - fee * min(yes_price, 1 - yes_price)
    edge_no = (1 - p_yes) - no_price - fee * min(no_price, 1 - no_price)
    if edge_yes >= edge_no:
        return {"best_side": "YES", "edge": round(edge_yes, 3),
                "p_win": round(p_yes, 3), "p_market": round(yes_price, 3)}
    return {"best_side": "NO", "edge": round(edge_no, 3),
            "p_win": round(1 - p_yes, 3), "p_market": round(no_price, 3)}


def bet_size_usd(edge, side_price):
    if not edge or edge <= 0 or not side_price or side_price <= 0 or side_price >= 1:
        return 0.0
    kelly = (edge / (1 - side_price)) * KELLY_FRACTION
    return round(min(BANKROLL_USD * max(0, kelly), TRADE_CAP_USD), 2)


def maker_fits(side_price, bet_usd):
    """A £1-ish maker order needs >= 5 shares, so it only fits cheap prices."""
    if not side_price or side_price <= 0:
        return False
    shares = bet_usd / side_price
    return shares >= MIN_SHARES


# ---------- polymarket markets ----------
def _prices(market):
    outcomes, prices = market.get("outcomes"), market.get("outcomePrices")
    if isinstance(outcomes, str): outcomes = json.loads(outcomes)
    if isinstance(prices, str): prices = json.loads(prices)
    if not outcomes or not prices:
        return None, None
    d = {o.lower(): float(p) for o, p in zip(outcomes, prices)}
    return d.get("yes"), d.get("no")


def fetch_temp_markets(max_pages=6, page=200):
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


def _lead_days(market_date, today):
    try:
        return (date.fromisoformat(market_date) - date.fromisoformat(today)).days
    except Exception:
        return None


def build_edge_table():
    """Ranked live weather-edge opportunities, ensemble-driven, maker-fit filtered."""
    markets = fetch_temp_markets()
    parsed_all = [(m, parse_question(m["question"])) for m in markets]
    parsed_all = [(m, p) for m, p in parsed_all if p and p["city"] in CITY_COORDS]
    # each city's unit = whatever its markets are quoted in (US=F, else C).
    # If a city somehow has both, prefer F (US markets); consistent per-city in practice.
    units = {}
    for _, p in parsed_all:
        c, u = p["city"], p.get("unit", "C")
        if c not in units or u == "F":
            units[c] = u

    wx = fetch_weather(units)
    ens_high = fetch_ensemble(units, is_low=False)
    ens_low = fetch_ensemble(units, is_low=True)

    rows = []
    for m, parsed in parsed_all:
        city = parsed["city"]
        is_low = parsed["kind"] == "lowest"
        w = wx.get(city, {})
        today = (w.get("local_time", "") or "").split("T")[0] or None
        fallback_year = int(today.split("-")[0]) if today else datetime.utcnow().year
        market_date = parse_date(parsed["date_str"], fallback_year)
        if market_date and today and market_date < today:
            continue  # stale
        lead = _lead_days(market_date, today) if (market_date and today) else None

        members = (ens_low if is_low else ens_high).get(city, {}).get(market_date)
        p_yes = bucket_probability(members, parsed) if members else None

        yes_p, no_p = _prices(m)
        pe = price_edge(p_yes, yes_p, no_p, maker=True)
        side_price = (yes_p if pe["best_side"] == "YES" else no_p) or 0
        bet = bet_size_usd(pe["edge"], side_price)
        fits = maker_fits(side_price, bet) if bet else False

        liquid = bool(yes_p and no_p and 0.05 <= yes_p <= 0.95 and 0.05 <= no_p <= 0.95)
        vol = float(m.get("volume") or 0)
        # tight selection: REAL edge (not stale-price artifact), liquid book,
        # out of the dead-zone, maker-fittable, near-term.
        actionable = bool(
            pe["edge"] and EDGE_THRESHOLD < pe["edge"] <= EDGE_SANITY_CAP
            and p_yes is not None
            and liquid and vol >= VOLUME_FLOOR
            and lead is not None and 0 <= lead <= MAX_LEAD_DAYS
            and side_price and (side_price <= 0.40 or side_price >= 0.60)  # skip dead-zone
            and fits
        )

        ev = m.get("events")
        slug = (ev[0].get("slug") if isinstance(ev, list) and ev else None) or m.get("slug")
        st = station_for(city)
        reason = (build_reasoning(parsed, members, p_yes, pe, lead, bool(st and st[2]))
                  if (p_yes is not None and pe["best_side"]) else
                  {"reasoning": "Not enough forecast data to form a view.", "confidence": "—", "conf_model_pct": None})
        rows.append({
            "question": m["question"], "city": city, "threshold_c": parsed["threshold_c"],
            "kind": parsed["kind"], "date_str": parsed["date_str"], "market_date": market_date,
            "lead_days": lead,
            "station_confirmed": bool(st and st[2]),
            "members": len(members) if members else 0,
            "model_prob": round(p_yes, 3) if p_yes is not None else None,
            "high_so_far_c": w.get("low_so_far_c") if is_low else w.get("high_so_far_c"),
            "yes_price": yes_p, "no_price": no_p,
            "volume_usd": round(float(m.get("volume") or 0)),
            "bet_usd": bet, "maker_fits": fits,
            "actionable": actionable,
            "liquid": liquid,
            "poly_url": f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com",
            **pe, **reason,
        })
    # actionable first, then by edge
    rows.sort(key=lambda r: (not r["actionable"], -(r.get("edge") or -999)))
    return rows


if __name__ == "__main__":
    t = build_edge_table()
    act = [r for r in t if r["actionable"]]
    print(f"{len(t)} temp markets | {len(act)} ACTIONABLE (ensemble edge, maker-fit)")
    for r in act[:8]:
        print(f"  {r['best_side']} {r['city']} {r['threshold_c']}° "
              f"model={r['model_prob']} mkt={r['p_market']} edge={r['edge']} "
              f"bet=${r['bet_usd']} lead={r['lead_days']}d station={'✓' if r['station_confirmed'] else '~'}")
