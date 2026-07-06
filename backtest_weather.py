"""Historical backtest of the weather-edge method — does it actually work?

Answers the core question BEFORE risking money: when our model says a temperature
bucket has probability P, does it actually happen ~P of the time? (calibration),
and how sharp are the predictions? (Brier score).

Data (all free, Open-Meteo):
  - Actual observed daily highs      -> archive-api        (ground truth)
  - The forecast that was available   -> historical-forecast-api (what we'd have used)

For each city and day over the past ~90 days, and each temperature bucket around
the forecast, we compute our predicted probability and check it against what
actually happened. Then we aggregate calibration + accuracy across thousands of
city-day-bucket points.

Note: historical ENSEMBLE members aren't available, so we use the archived
deterministic forecast + our Normal(sigma) uncertainty. This tests the
forecast->probability method that underpins the live ensemble version.

Run: python backtest_weather.py
"""
import math
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor

import requests

from strategies.weather_edge import RESOLUTION_STATION, CITY_COORDS, MEMBER_SIGMA

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
HISTFC = "https://historical-forecast-api.open-meteo.com/v1/forecast"
DAYS = 90
SIGMA = MEMBER_SIGMA  # same uncertainty the live model uses

# use the station coord where known, else city centre
STATIONS = {c: (RESOLUTION_STATION.get(c) or CITY_COORDS[c]) for c in CITY_COORDS}


def _cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def bucket_prob(T, fc, s=SIGMA):
    """Our model's P(actual high lands in the exact 1-degree bucket [T, T+1))."""
    return _cdf((T + 1 - fc) / s) - _cdf((T - fc) / s)


def _series(url, lat, lon, start, end):
    r = requests.get(url, params={
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "daily": "temperature_2m_max", "timezone": "auto"}, timeout=30)
    r.raise_for_status()
    d = r.json().get("daily", {})
    return dict(zip(d.get("time", []), d.get("temperature_2m_max", [])))


def city_records(args):
    city, (lat, lon), start, end = args
    try:
        actual = _series(ARCHIVE, lat, lon, start, end)
        fc = _series(HISTFC, lat, lon, start, end)
    except Exception:
        return []
    recs = []
    for dt, a in actual.items():
        f = fc.get(dt)
        if a is None or f is None:
            continue
        for T in range(round(f) - 5, round(f) + 6):
            recs.append((bucket_prob(T, f), 1 if T <= a < T + 1 else 0))
    return recs


def main():
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=DAYS)
    s, e = start.isoformat(), end.isoformat()
    cities = list(STATIONS.items())
    args = [(c, coord, s, e) for c, coord in cities]

    print(f"Backtesting {len(cities)} cities over {DAYS} days ({s} -> {e})…\n")
    all_recs = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for recs in ex.map(city_records, args):
            all_recs.extend(recs)

    if not all_recs:
        print("no data"); return

    # Brier score (lower = sharper & better calibrated)
    brier = sum((p - h) ** 2 for p, h in all_recs) / len(all_recs)

    # calibration table: bucket predictions into bands, compare predicted vs actual
    bands = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5), (0.5, 1.01)]
    print(f"{'predicted band':<16}{'avg predicted':>14}{'actually won':>14}{'n':>8}")
    print("-" * 52)
    for lo, hi in bands:
        b = [(p, h) for p, h in all_recs if lo <= p < hi]
        if not b:
            continue
        avg_pred = sum(p for p, _ in b) / len(b)
        actual = sum(h for _, h in b) / len(b)
        flag = "  ✓" if abs(avg_pred - actual) < 0.05 else "  ← off"
        print(f"{int(lo*100)}-{int(hi*100)}%{'':<10}{avg_pred*100:>12.1f}%{actual*100:>13.1f}%{len(b):>8}{flag}")

    print("-" * 52)
    print(f"\nBrier score: {brier:.4f}   (0 = perfect, 0.25 = coin-flip baseline)")
    print(f"Data points: {len(all_recs):,} city-day-bucket predictions")
    print("\nIf 'avg predicted' ≈ 'actually won' in every band, the model is")
    print("CALIBRATED — its probabilities are trustworthy, which is the whole game.")


if __name__ == "__main__":
    main()
