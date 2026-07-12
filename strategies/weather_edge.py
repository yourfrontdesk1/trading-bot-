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
import os
import re
import json
import time
import math
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor

import requests

import config

GAMMA = "https://gamma-api.polymarket.com"
FORECAST_API = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_API = "https://ensemble-api.open-meteo.com/v1/ensemble"
# ERA5 reanalysis — used to SETTLE past bets. Chosen deliberately: (a) it serves
# any past date (the forecast API returns nothing beyond ~92 days), and (b) sigma
# was fitted against ERA5 actuals in calibrate_sigma.py, so grading on ERA5 keeps
# the yardstick that scores bets identical to the one the model was tuned against.
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"

# --- real bankroll for a £30 stake (~$38), £1 (~$1.25) bets ---
BANKROLL_USD = 38.0
TRADE_CAP_USD = 2.0
KELLY_FRACTION = 0.25          # quarter-Kelly
EDGE_THRESHOLD = 0.08          # only trade if model_prob - price > this
EDGE_SANITY_CAP = 0.35         # edges above this = stale/illiquid price, not a real edge
VOLUME_FLOOR = 1000            # drop thin, stale-priced markets. Polymarket temp
                               # markets top out ~$10k (the $10k floor the pros use is
                               # Kalshi-scale); measured, temp markets split cleanly into
                               # a liquid cluster >=$5k and thin junk <$1k, so $1k keeps
                               # the real books and cuts the stale-price artifacts.
TAIL_MAX_PRICE = 0.15          # a "cheap tail": the winning weather traders concentrate
                               # here (side priced <=~$0.15) — low hit-rate, big payouts,
                               # +EV at volume. We tag/prioritise these.
MAKER_FEE = 0.0                # resting limit orders are fee-free on Polymarket
TAKER_FEE_RATE = 0.02          # market orders cost ~feeRate * min(p,1-p); we avoid these
MIN_SHARES = 5                 # Polymarket minimum order size
MAX_LEAD_DAYS = 3              # forecasts past ~3 days are too noisy to trust
MAX_EXPOSURE = 0.6             # never risk more than 60% of bankroll at once
# TRIMMED to the single 31-member GFS ensemble to stay under the free weather API's
# DAILY cap so the bot runs all day without going dark. A 3-model blend
# (gfs025,ecmwf_ifs025,icon_global_eps = 122 members) is sharper but ~3x the API cost
# and exhausts the free tier — re-enable it when on a paid weather API. Ids must be
# exact Open-Meteo ensemble ids (VALID_ENSEMBLE_MODELS guards typos like icon_global).
ENSEMBLE_MODELS = "gfs025"
VALID_ENSEMBLE_MODELS = {
    "gfs025", "gfs05", "aigefs025", "ecmwf_ifs025", "ecmwf_aifs025",
    "icon_seamless_eps", "icon_global_eps", "icon_eu_eps", "icon_d2_eps",
    "gem_global", "bom_access_global",
}
MEMBER_SIGMA = 1.2          # per-member forecast uncertainty (°). FITTED, not guessed:
                            # strategies/calibrate_sigma.py backtests 610 station-days of
                            # archived forecast vs ERA5 actuals at the real settlement
                            # stations — day-ahead high RMSE is 1.44C, and sigma=1.2
                            # minimises the Brier score (0.087). The old 0.6 was <half the
                            # true error, which made the model overconfident and invented
                            # fake NO edges. 1.2 is a floor; nudge up for extra safety.

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

CACHE_TTL = 3600               # 1h — the free weather API has a hard DAILY call cap,
                               # so cache aggressively; forecasts barely move in an hour.
_wx_cache, _wx_ts, _wx_sig = {}, 0.0, None
_ens_cache, _ens_ts, _ens_sig = {}, {}, {}  # per-key (high/low fetched separately)

# Whether the last ensemble fetch hit the weather API's hard daily cap. Lets the
# dashboard say "data unavailable — resets tomorrow" instead of the lie "no edge
# found" when the truth is the model couldn't fetch a single forecast.
_ENSEMBLE_LIMITED = False


def reset_data_status():
    global _ENSEMBLE_LIMITED
    _ENSEMBLE_LIMITED = False


def ensemble_rate_limited():
    return _ENSEMBLE_LIMITED


def _cache_sig(units):
    """A signature of exactly what a fetch would cover: each city, its unit, and
    the coords/station it currently resolves to. If any of these change, the old
    cache no longer covers the request and must be refetched — TTL alone isn't
    enough (a new day's markets add cities the stale blob is missing)."""
    return tuple(sorted((c, u, station_for(c)) for c, u in units.items()))


def _cache_fresh(cache, cached_sig, cached_ts, sig, now, ttl=CACHE_TTL):
    """Fresh only if we actually have data, it covers the SAME request, and it
    hasn't aged out."""
    return bool(cache) and cached_sig == sig and (now - cached_ts) < ttl


def _ometeo_unit(u):
    return "fahrenheit" if u == "F" else "celsius"


def ometeo_endpoint(free_url):
    """Given a free Open-Meteo URL, return (url, extra_params). With a paid API key
    set, swap to the uncapped 'customer-' host and attach the key — this is what
    lets the bot run constantly instead of dying at the free daily cap. Without a
    key, returns the free URL unchanged."""
    key = config.OPENMETEO_API_KEY
    if not key:
        return free_url, {}
    customer = free_url.replace("https://", "https://customer-", 1)
    return customer, {"apikey": key}


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


# --- latency arbitrage: bet right when fresh model data lands, before the market
# reprices. GFS/ECMWF ensembles run at 00/06/12/18 UTC and Open-Meteo publishes the
# processed data ~5h later, so fresh forecasts appear ~05/11/17/23 UTC. Scanning just
# after these beats scanning on a dumb fixed timer into stale prices. ---
MODEL_RELEASE_UTC_HOURS = (5, 11, 17, 23)


def seconds_until_next_release(now):
    """Seconds from `now` (a naive UTC datetime) to the next model-release window."""
    cur = now.hour * 3600 + now.minute * 60 + now.second
    releases = sorted(h * 3600 for h in MODEL_RELEASE_UTC_HOURS)
    for r in releases:
        if r > cur:
            return r - cur
    return releases[0] + 86400 - cur   # wrap to the first window tomorrow


def resolve_market_date(date_str, today_iso):
    """Turn a 'Month Day' string into an ISO date, choosing the calendar year
    (this / next / previous) that lands nearest `today`. Without this, a market
    dated 'January 2' seen on Dec 30 resolves to this-year-January — ~360 days in
    the past — and gets wrongly dropped as stale right when it's most tradeable."""
    if not today_iso:
        return None
    y = int(today_iso[:4])
    ref = date.fromisoformat(today_iso)
    best = None
    for yr in (y, y + 1, y - 1):
        d = parse_date(date_str, yr)
        if not d:
            continue
        delta = (date.fromisoformat(d) - ref).days
        if best is None or abs(delta) < abs(best[1]):
            best = (d, delta)
    return best[0] if best else None


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


# ---- settlement-station resolution straight from each market's description ----
# Every temp market's description names the exact airport it settles on and links
# its Wunderground page, whose URL ends in the station's 4-letter ICAO code
# (e.g. .../history/daily/cn/chongqing/ZUCK). We resolve that ICAO to real coords
# via a cached OurAirports table, so the forecast is pulled for the SAME station
# the market pays on — not a city-centre guess that can be 1-3° off.
_ICAO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "brokers", "_airports_icao.json")
_ICAO_COORDS = None
_RUN_STATION = {}   # city -> (lat, lon, station_name); rebuilt each scan
_RUN_ICAO = {}      # city -> settlement-station ICAO; rebuilt each scan


def _icao_table():
    global _ICAO_COORDS
    if _ICAO_COORDS is None:
        try:
            with open(_ICAO_PATH) as f:
                _ICAO_COORDS = json.load(f)
        except Exception:
            _ICAO_COORDS = {}
    return _ICAO_COORDS


# ICAO is the last URL segment; require 4 UPPERCASE letters so the city slug
# (e.g. "new-york-city") can't be mistaken for a station code.
_ICAO_RE = re.compile(r"wunderground\.com/history/daily/[a-z]{2}/[a-z0-9-]+/([A-Z]{4})\b")
_STATION_RE = re.compile(r"recorded at the (.+?) Station", re.I)


def station_from_description(desc):
    """(lat, lon, name) of the market's real settlement station, or None."""
    if not desc:
        return None
    m = _ICAO_RE.search(desc)
    nm = _STATION_RE.search(desc)
    if m:
        coords = _icao_table().get(m.group(1))
        if coords:
            return (coords[0], coords[1], (nm.group(1) if nm else m.group(1)))
    return None


def icao_from_description(desc):
    """The 4-letter ICAO of the market's settlement station, or None — used to pull
    the actual METAR observation the market settles on."""
    if not desc:
        return None
    m = _ICAO_RE.search(desc)
    return m.group(1) if m else None


def station_for(city):
    """Return (lat, lon, confirmed) — resolution station if known, else city centre."""
    if city in _RUN_STATION:                       # resolved from the market itself
        lat, lon, _name = _RUN_STATION[city]
        return (lat, lon, True)
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
        url, extra = ometeo_endpoint(FORECAST_API)
        r = requests.get(url, params={
            "latitude": lat, "longitude": lon, "current": "temperature_2m",
            "hourly": "temperature_2m", "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": "auto", "forecast_days": 2, "temperature_unit": _ometeo_unit(unit),
            **extra},
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
    global _wx_cache, _wx_ts, _wx_sig
    sig = _cache_sig(units)
    if _cache_fresh(_wx_cache, _wx_sig, _wx_ts, sig, time.time()):
        return _wx_cache
    out = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for city, data in ex.map(_fetch_weather_one, list(units.items())):
            if data:
                out[city] = data
    _wx_cache, _wx_ts, _wx_sig = out, time.time(), sig
    return out


# ---------- ensemble (the real probability distribution) ----------
def fetch_ensemble(units, is_low=False):
    """Return {city: {date: [member temps]}} from the 82-member GFS+ECMWF blend,
    fetched in each city's native unit."""
    global _ens_cache, _ens_ts, _ens_sig
    key = "low" if is_low else "high"
    sig = _cache_sig(units)
    cache = _ens_cache.get(key)
    if _cache_fresh(cache, _ens_sig.get(key), _ens_ts.get(key, 0), sig, time.time()):
        return cache
    var = "temperature_2m_min" if is_low else "temperature_2m_max"

    def one(args):
        city, unit = args
        loc = station_for(city)
        if not loc:
            return city, None
        lat, lon, _ = loc
        try:
            url, extra = ometeo_endpoint(ENSEMBLE_API)
            r = requests.get(url, params={
                "latitude": lat, "longitude": lon, "daily": var,
                "models": ENSEMBLE_MODELS, "forecast_days": 5, "timezone": "auto",
                "temperature_unit": _ometeo_unit(unit), **extra},
                headers={"User-Agent": "tradingbot/0.2"}, timeout=25)
            if r.status_code == 429:   # hard daily cap — record it so the UI is honest
                global _ENSEMBLE_LIMITED
                _ENSEMBLE_LIMITED = True
                return city, None
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
    _ens_sig[key] = sig
    return out


def resolves_yes(parsed, temp):
    """THE canonical settlement rule — the single source of truth for whether an
    observed temperature `temp` settles a market YES. Both the model (P(win)) and
    the ledger (did-we-win) MUST route through this, or calibration measures noise.

    Wunderground reports the daily high/low as a ROUNDED integer and the market
    resolves to the range containing it, so YES iff round(temp) satisfies the
    condition (half-open intervals match round-half-up):
      "be T"           -> round(temp) == T  <=>  T-0.5 <= temp <  T+0.5
      "be T or higher" -> round(temp) >= T  <=>       temp >= T-0.5
      "be T or below"  -> round(temp) <= T  <=>       temp <  T+0.5
    """
    T = parsed["threshold_c"]
    if parsed["or_higher"]:
        return temp >= T - 0.5
    if parsed["or_below"]:
        return temp < T + 0.5
    return T - 0.5 <= temp < T + 0.5


def bucket_hits(members, parsed):
    """How many ensemble members land in the YES outcome (same rule as settlement)."""
    return sum(1 for m in members if resolves_yes(parsed, m))


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

    # Wunderground rounds to an integer, market resolves to the range CONTAINING
    # it: the T° outcome = true temp in [T-0.5, T+0.5). Bucket edges are centred
    # on T, not offset by a full degree as before.
    def p_member(mv):
        if parsed["or_higher"]:          # rounds to >= T  <=> true temp >= T-0.5
            return 1 - _cdf((T - 0.5 - mv) / s)
        if parsed["or_below"]:           # rounds to <= T  <=> true temp < T+0.5
            return _cdf((T + 0.5 - mv) / s)
        return _cdf((T + 0.5 - mv) / s) - _cdf((T - 0.5 - mv) / s)  # rounds-to-T

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


# ---------- self-learning: features shared by the ledger and the selector ----------
def bet_features(feat):
    """Stable category tags describing a bet. The SAME tags are computed for a
    resolved bet (so the ledger can see which categories actually lose) and for a
    live candidate (so selection can refuse categories the record has proven bad).
    One tag from each axis. feat keys: station_confirmed(bool), is_exact(bool),
    lead_days(int|None), side('YES'/'NO'), edge(float)."""
    ld = feat.get("lead_days")
    edge = feat.get("edge") or 0
    sp = feat.get("side_price")
    tags = {
        "confirmed_station" if feat.get("station_confirmed") else "unconfirmed_station",
        "exact_bucket" if feat.get("is_exact") else "open_ended",
        "lead_0_1" if (ld is not None and ld <= 1) else "lead_2plus",
        "side_" + (feat.get("side") or "?"),
        "small_edge" if edge <= 0.12 else "big_edge",
    }
    if sp is not None:   # cheap-tail axis only when we know the price paid
        tags.add("cheap_tail" if 0 < sp <= TAIL_MAX_PRICE else "not_tail")
    return tags


def is_actionable(c, avoid=()):
    """The single, pure selection rule (also unit-tested): should we actually rest
    a maker bet on candidate `c`? Keeps the criteria in one place instead of a
    ten-line boolean buried in build_edge_table. `c` carries edge, model_prob,
    liquid, volume, lead, side_price, maker_fits + the bet_features inputs."""
    edge, sp, lead = c.get("edge"), c.get("side_price"), c.get("lead")
    if not (edge and EDGE_THRESHOLD < edge <= EDGE_SANITY_CAP):
        return False
    if c.get("model_prob") is None:
        return False
    if not c.get("liquid") or (c.get("volume") or 0) < VOLUME_FLOOR:
        return False
    if lead is None or not (0 <= lead <= MAX_LEAD_DAYS):
        return False
    if not sp or not (sp <= 0.40 or sp >= 0.60):   # skip the fee/liquidity dead-zone
        return False
    if not c.get("maker_fits"):
        return False
    feat = {"station_confirmed": c.get("station_confirmed"), "is_exact": c.get("is_exact"),
            "lead_days": lead, "side": c.get("side"), "edge": edge, "side_price": sp}
    if bet_features(feat) & set(avoid or ()):      # a learned-loser category
        return False
    return True


def passes_lessons(feat, avoid):
    """False iff this bet falls in a category the resolved record has proven to
    lose (a learned 'avoid' tag). Empty avoid set => everything passes."""
    return not (bet_features(feat) & set(avoid or ()))


# ---------- polymarket markets ----------
def _prices(market):
    outcomes, prices = market.get("outcomes"), market.get("outcomePrices")
    if isinstance(outcomes, str): outcomes = json.loads(outcomes)
    if isinstance(prices, str): prices = json.loads(prices)
    if not outcomes or not prices:
        return None, None
    d = {o.lower(): float(p) for o, p in zip(outcomes, prices)}
    return d.get("yes"), d.get("no")


def _token_ids(market):
    """{outcome.lower(): clob_token_id} — the on-chain order token per outcome.
    Empty if the market doesn't expose an order book we could rest into."""
    ids, outs = market.get("clobTokenIds"), market.get("outcomes")
    if isinstance(ids, str): ids = json.loads(ids)
    if isinstance(outs, str): outs = json.loads(outs)
    if not ids or not outs:
        return {}
    return {o.lower(): t for o, t in zip(outs, ids)}


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


def build_edge_table(avoid=()):
    """Ranked live weather-edge opportunities, ensemble-driven, maker-fit filtered.

    `avoid` is the set of learned-bad category tags from ledger.lessons(): any
    candidate falling in one is demoted out of 'actionable' so the bot stops
    repeating a category its own track record has proven to lose."""
    reset_data_status()   # clears the rate-limit flag; fetch_ensemble re-sets it if hit
    markets = fetch_temp_markets()
    parsed_all = [(m, parse_question(m["question"])) for m in markets]
    parsed_all = [(m, p) for m, p in parsed_all if p]
    # resolve each market's ACTUAL settlement station from its own description,
    # so forecast + ensemble are pulled for that airport (not the city centre).
    global _RUN_STATION, _RUN_ICAO
    _RUN_STATION, _RUN_ICAO = {}, {}
    for m, p in parsed_all:
        st = station_from_description(m.get("description"))
        if st:
            _RUN_STATION[p["city"]] = st
        ic = icao_from_description(m.get("description"))
        if ic:
            _RUN_ICAO[p["city"]] = ic
    # keep any market we can actually locate: resolved station OR known city centre
    parsed_all = [(m, p) for m, p in parsed_all
                  if p["city"] in _RUN_STATION or p["city"] in CITY_COORDS]
    # Only spend weather-API budget on cities that have a LIQUID market — there's no
    # point pulling forecasts for cities too thin to ever bet, and it's what keeps
    # burning the free daily cap. Cuts calls ~2-3x so Open-Meteo stays uncapped.
    liquid_cities = {p["city"] for m, p in parsed_all
                     if float(m.get("volume") or 0) >= VOLUME_FLOOR}
    if liquid_cities:
        parsed_all = [(m, p) for m, p in parsed_all if p["city"] in liquid_cities]
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
        market_date = (resolve_market_date(parsed["date_str"], today) if today
                       else parse_date(parsed["date_str"], datetime.utcnow().year))
        if market_date and today and market_date < today:
            continue  # stale
        lead = _lead_days(market_date, today) if (market_date and today) else None

        members = (ens_low if is_low else ens_high).get(city, {}).get(market_date)
        data_source = "ensemble"
        if not members and market_date:
            # Open-Meteo ensemble unavailable (e.g. daily cap spent) — keep the bot
            # alive with the free, uncapped providers (Met.no global + NWS US).
            from strategies.providers import multi_forecast
            loc = station_for(city)
            if loc:
                members = multi_forecast(loc[0], loc[1], market_date, is_low, parsed["unit"])
                data_source = "free-fallback" if members else "ensemble"
        p_yes = bucket_probability(members, parsed) if members else None

        yes_p, no_p = _prices(m)
        pe = price_edge(p_yes, yes_p, no_p, maker=True)
        side_price = (yes_p if pe["best_side"] == "YES" else no_p) or 0
        bet = bet_size_usd(pe["edge"], side_price)
        fits = maker_fits(side_price, bet) if bet else False

        liquid = bool(yes_p and no_p and 0.05 <= yes_p <= 0.95 and 0.05 <= no_p <= 0.95)
        vol = float(m.get("volume") or 0)
        st = station_for(city)
        is_exact = not parsed["or_higher"] and not parsed["or_below"]
        cheap_tail = bool(side_price and 0 < side_price <= TAIL_MAX_PRICE)
        feat = {"station_confirmed": bool(st and st[2]), "is_exact": is_exact,
                "lead_days": lead, "side": pe["best_side"], "edge": pe["edge"],
                "side_price": side_price}
        # a category the track record has proven to lose (see ledger.lessons):
        # keep the row but never mark it actionable.
        blocked_by = sorted(bet_features(feat) & set(avoid or ()))
        candidate = {"edge": pe["edge"], "model_prob": p_yes, "liquid": liquid,
                     "volume": vol, "lead": lead, "side_price": side_price,
                     "maker_fits": fits, **feat}
        actionable = is_actionable(candidate, avoid)

        ev = m.get("events")
        slug = (ev[0].get("slug") if isinstance(ev, list) and ev else None) or m.get("slug")
        token_id = _token_ids(m).get(pe["best_side"].lower()) if pe["best_side"] else None
        reason = (build_reasoning(parsed, members, p_yes, pe, lead, bool(st and st[2]))
                  if (p_yes is not None and pe["best_side"]) else
                  {"reasoning": "Not enough forecast data to form a view.", "confidence": "—", "conf_model_pct": None})
        rows.append({
            "question": m["question"], "city": city, "threshold_c": parsed["threshold_c"],
            "kind": parsed["kind"], "date_str": parsed["date_str"], "market_date": market_date,
            "lead_days": lead,
            "station_confirmed": bool(st and st[2]),
            "station_icao": _RUN_ICAO.get(city),   # for settling on the real METAR obs
            "members": len(members) if members else 0,
            "data_source": data_source,
            "model_prob": round(p_yes, 3) if p_yes is not None else None,
            "high_so_far_c": w.get("low_so_far_c") if is_low else w.get("high_so_far_c"),
            "yes_price": yes_p, "no_price": no_p,
            "volume_usd": round(float(m.get("volume") or 0)),
            "bet_usd": bet, "maker_fits": fits,
            "actionable": actionable,
            "liquid": liquid,
            "cheap_tail": cheap_tail,  # side priced <= TAIL_MAX_PRICE — the pros' zone
            "token_id": token_id,      # CLOB order token for the chosen side
            "blocked_by": blocked_by,  # learned-loser tags that vetoed this bet, if any
            "poly_url": f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com",
            **pe, **reason,
        })
    # actionable first, then cheap tails (where the documented edge lives), then edge
    rows.sort(key=lambda r: (not r["actionable"], not r.get("cheap_tail"),
                             -(r.get("edge") or -999)))
    return rows


if __name__ == "__main__":
    t = build_edge_table()
    act = [r for r in t if r["actionable"]]
    print(f"{len(t)} temp markets | {len(act)} ACTIONABLE (ensemble edge, maker-fit)")
    for r in act[:8]:
        print(f"  {r['best_side']} {r['city']} {r['threshold_c']}° "
              f"model={r['model_prob']} mkt={r['p_market']} edge={r['edge']} "
              f"bet=${r['bet_usd']} lead={r['lead_days']}d station={'✓' if r['station_confirmed'] else '~'}")
