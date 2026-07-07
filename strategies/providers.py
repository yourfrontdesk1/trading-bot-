"""Free, no-signup weather sources — blended into a cross-provider mini-ensemble.

The point: (1) no single provider's daily cap can take the bot down, and (2)
independent models blended together give a better probability estimate than one.
None of these need an API key or an account.

  - Met.no (MET Norway): GLOBAL, no key, hourly forecast.
  - NWS (api.weather.gov): US only, no key, no cap.

These are used as a resilient FALLBACK when the Open-Meteo ensemble is unavailable
(e.g. its free daily cap is spent), so the bot keeps producing forecasts 24/7.
"""
from datetime import datetime, timezone

import requests

UA = {"User-Agent": "trading-bot/0.3 (leonthick717@gmail.com)"}
AVIATIONWEATHER = "https://aviationweather.gov/api/data/metar"


def _c2f(c):
    return c * 9 / 5 + 32


def _f2c(f):
    return (f - 32) * 5 / 9


def metno_daily(lat, lon, date_iso, is_low, unit):
    """Daily high (or low) at a location for `date_iso` from MET Norway. Global, no
    key. Returns the temp in the market's `unit`, or None on any failure.

    Note: Met.no timestamps are UTC; we bucket by UTC date, so for cities far from
    UTC the daily extreme can be off by the few hours near the date boundary. Fine
    for a keep-alive fallback — the primary Open-Meteo path uses local time."""
    try:
        r = requests.get("https://api.met.no/weatherapi/locationforecast/2.0/compact",
                         params={"lat": round(lat, 4), "lon": round(lon, 4)},
                         headers=UA, timeout=20)
        r.raise_for_status()
        ts = r.json()["properties"]["timeseries"]
        vals = [t["data"]["instant"]["details"]["air_temperature"]
                for t in ts if t["time"].startswith(date_iso)
                and "air_temperature" in t["data"]["instant"]["details"]]
        if not vals:
            return None
        c = min(vals) if is_low else max(vals)   # Met.no reports Celsius
        return _c2f(c) if unit == "F" else c
    except Exception:
        return None


def nws_daily(lat, lon, date_iso, is_low, unit):
    """Daily high (or low) from the US National Weather Service. US only (returns
    None elsewhere), no key, no cap. Temp in the market's `unit`, or None."""
    try:
        p = requests.get(f"https://api.weather.gov/points/{round(lat, 4)},{round(lon, 4)}",
                         headers=UA, timeout=20)
        if p.status_code != 200:
            return None   # outside US coverage
        furl = p.json()["properties"]["forecast"]
        periods = requests.get(furl, headers=UA, timeout=20).json()["properties"]["periods"]
        want_daytime = not is_low   # daytime period = the day's high; night = low
        cand = [x for x in periods if x.get("startTime", "").startswith(date_iso)
                and x.get("isDaytime") == want_daytime]
        if not cand:
            return None
        t = cand[0]["temperature"]
        is_c = cand[0].get("temperatureUnit") == "C"
        c = t if is_c else _f2c(t)
        return (_c2f(c) if unit == "F" else c)
    except Exception:
        return None


def _daily_from_metar(obs, date_iso, is_low, unit):
    """Pure: the observed daily high/low for date_iso from a list of METAR obs
    dicts (each {temp: °C, obsTime: unix}). Bucketed by UTC date."""
    vals = []
    for o in obs:
        t, ot = o.get("temp"), o.get("obsTime")
        if t is None or ot is None:
            continue
        if datetime.fromtimestamp(ot, tz=timezone.utc).strftime("%Y-%m-%d") == date_iso:
            vals.append(t)
    if not vals:
        return None
    c = min(vals) if is_low else max(vals)
    return _c2f(c) if unit == "F" else c


def metar_daily(icao, date_iso, is_low, unit="C", hours=72):
    """The ACTUAL settlement observation: daily high/low at a station's METAR — the
    same source Wunderground derives its number from. Free, global, no key. Covers
    ~the last 3 days (enough to settle a bet within a day of resolution). Returns
    the value in the market's `unit`, or None.

    US caveat: METAR temp is whole °C; for °F markets we convert (±~0.9°F), which
    can rarely flip a 1°F bucket — so the ledger falls back to ERA5 if this is None."""
    if not icao:
        return None
    try:
        r = requests.get(AVIATIONWEATHER, params={"ids": icao, "format": "json", "hours": hours},
                         headers=UA, timeout=20)
        r.raise_for_status()
        return _daily_from_metar(r.json(), date_iso, is_low, unit)
    except Exception:
        return None


DEFAULT_PROVIDERS = (metno_daily, nws_daily)


def combine(forecasts):
    """Drop failed (None) provider results; the survivors are the ensemble members
    fed to bucket_probability (each treated as Normal(member, sigma))."""
    return [f for f in forecasts if f is not None]


def multi_forecast(lat, lon, date_iso, is_low, unit, providers=DEFAULT_PROVIDERS):
    """Query every free provider and return the list of forecasts that succeeded —
    a small cross-provider ensemble. Empty list if all sources fail."""
    return combine([p(lat, lon, date_iso, is_low, unit) for p in providers])
