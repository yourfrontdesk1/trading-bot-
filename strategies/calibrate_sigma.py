"""Calibrate MEMBER_SIGMA from real data instead of guessing it.

The weather-edge model turns a forecast into P(daily high rounds to T) using a
Normal(mean=forecast, sd=MEMBER_SIGMA). If sigma is too small the model is
overconfident and invents fake edges (exactly the Buenos Aires / Madrid bug);
too large and every probability mushes to the base rate. The right sigma is the
one that makes the model's probabilities CALIBRATED against what actually happened.

Method (no future data, no ensemble-archive needed):
  truth    : ERA5 archive daily high at the real settlement station.
  forecast : the model's OWN archived forecast for that same day (historical-
             forecast-api) — a fair proxy for the day-ahead ensemble mean.
  For each (station, day) and each integer threshold T within +/-4 of the
  forecast, the market bet is "does the high round to T?". The model predicts
  P(bucket T) from Normal(forecast, sigma); the outcome is 1 iff round(actual)=T.
  We sweep sigma and pick the value that minimises the Brier score, then print a
  reliability table so you can SEE whether "80% confident" really wins ~80%.

Run:  python -m strategies.calibrate_sigma
"""
import json
import math
from concurrent.futures import ThreadPoolExecutor

import requests

from strategies.weather_edge import _icao_table, CITY_COORDS, MEMBER_SIGMA

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
HISTFC = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# A spread of real settlement stations (ICAO -> label) across climates, so the fit
# isn't dominated by one regime. Coords resolved from the cached OurAirports table.
STATIONS = {
    "RJTT": "Tokyo Haneda", "MMMX": "Mexico City", "LEMD": "Madrid Barajas",
    "SAEZ": "Buenos Aires Ezeiza", "EGLC": "London City", "KLGA": "New York LaGuardia",
    "EFHK": "Helsinki Vantaa", "ZUUU": "Chengdu", "OPKC": "Karachi", "LFPB": "Paris",
}
START, END = "2026-03-01", "2026-06-30"   # ~120-day out-of-season-agnostic window


def _cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def bucket_prob(forecast, T, sigma):
    """P(daily high rounds to integer T) = P(true temp in [T-0.5, T+0.5))."""
    return _cdf((T + 0.5 - forecast) / sigma) - _cdf((T - 0.5 - forecast) / sigma)


def _series(url, lat, lon):
    r = requests.get(url, params={
        "latitude": lat, "longitude": lon, "daily": "temperature_2m_max",
        "start_date": START, "end_date": END, "timezone": "auto"},
        headers={"User-Agent": "tradingbot/0.2"}, timeout=40)
    r.raise_for_status()
    d = r.json().get("daily", {})
    return dict(zip(d.get("time", []), d.get("temperature_2m_max", [])))


def _pairs_for(icao):
    coords = _icao_table().get(icao)
    if not coords:
        return []
    lat, lon = coords
    try:
        actual = _series(ARCHIVE, lat, lon)
        fc = _series(HISTFC, lat, lon)
    except Exception:
        return []
    out = []
    for day, a in actual.items():
        f = fc.get(day)
        if a is not None and f is not None:
            out.append((f, a))          # (forecast high, actual high)
    return out


def collect():
    pairs = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(_pairs_for, list(STATIONS)):
            pairs.extend(res)
    return pairs


def brier_for(pairs, sigma):
    """Mean Brier over every (day, threshold-within-+/-4) YES/NO bet."""
    tot, n = 0.0, 0
    for f, a in pairs:
        for T in range(round(f) - 4, round(f) + 5):
            p = min(0.999, max(0.001, bucket_prob(f, T, sigma)))
            # outcome via the SAME half-open [T-0.5,T+0.5) rule as resolves_yes /
            # settlement (round-half-up), NOT Python's banker's round().
            y = 1.0 if (T - 0.5 <= a < T + 0.5) else 0.0
            tot += (p - y) ** 2
            n += 1
    return tot / n if n else None


def reliability(pairs, sigma, nbins=10):
    """Bucket predictions by confidence; show predicted vs actual hit-rate."""
    counts = [0] * nbins
    psum = [0.0] * nbins
    hits = [0] * nbins
    for f, a in pairs:
        for T in range(round(f) - 4, round(f) + 5):
            p = min(0.999, max(0.001, bucket_prob(f, T, sigma)))
            b = min(nbins - 1, int(p * nbins))
            counts[b] += 1
            psum[b] += p
            hits[b] += 1 if (T - 0.5 <= a < T + 0.5) else 0
    rows = []
    for b in range(nbins):
        if counts[b]:
            rows.append((psum[b] / counts[b], hits[b] / counts[b], counts[b]))
    return rows


def main():
    print("collecting forecast-vs-actual pairs at real settlement stations...")
    pairs = collect()
    if not pairs:
        print("no data")
        return
    errs = [f - a for f, a in pairs]
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
    bias = sum(errs) / len(errs)
    print(f"{len(pairs)} station-days | forecast bias {bias:+.2f}C | RMSE {rmse:.2f}C\n")

    best = None
    print(f"{'sigma':>6} {'Brier':>8}")
    for s10 in range(4, 31):                # sigma 0.4 .. 3.0
        s = s10 / 10
        br = brier_for(pairs, s)
        mark = ""
        if best is None or br < best[1]:
            best = (s, br); mark = "  <-- best so far"
        print(f"{s:>6.1f} {br:>8.4f}{mark}")
    print(f"\nBEST sigma = {best[0]:.1f}  (Brier {best[1]:.4f})")
    print(f"current code uses MEMBER_SIGMA = {MEMBER_SIGMA}\n")

    print("reliability at fitted sigma (predicted -> actual hit-rate):")
    print(f"{'pred':>6} {'actual':>7} {'n':>7}")
    for pred, act, n in reliability(pairs, best[0]):
        flag = "" if abs(pred - act) < 0.05 else "  <-- miscalibrated"
        print(f"{pred:>6.2f} {act:>7.2f} {n:>7}{flag}")
    return best[0]


if __name__ == "__main__":
    main()
