"""Historical backtest of the weather-edge method — is the model actually calibrated?

Answers the core question BEFORE trusting it: when the model says a bucket has
probability P, does it happen ~P of the time? Uses the SAME canonical rule the live
bot settles on (weather_edge.resolves_yes + bucket_probability — single source of
truth), so the backtest measures what the bot actually trades. Also sweeps sigma to
find the best-calibrated value — a direct check on the "is 1.2 right / does applying
per-member sigma double-count?" question.

Data (all free, Open-Meteo):
  - Actual observed daily highs    -> archive-api (ground truth)
  - The forecast we'd have used     -> historical-forecast-api (single deterministic)

Caveat: historical ENSEMBLE members aren't available, so this tests the
single-forecast + sigma path (which is exactly the live FALLBACK path). It can't
measure profit — we have no historical market prices — only CALIBRATION, which is
the thing that determines whether an edge is real.

Run: python backtest_weather.py
"""
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor

import requests

import strategies.weather_edge as we
from strategies.weather_edge import RESOLUTION_STATION, CITY_COORDS, bucket_probability, resolves_yes

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
HISTFC = "https://historical-forecast-api.open-meteo.com/v1/forecast"
DAYS = 90
STATIONS = {c: (RESOLUTION_STATION.get(c) or CITY_COORDS[c]) for c in CITY_COORDS}


def _parsed(T):
    """An 'exactly T°' market in the shape the canonical helpers expect."""
    return {"kind": "highest", "threshold_c": T, "unit": "C",
            "or_higher": False, "or_below": False}


def _series(url, lat, lon, start, end):
    r = requests.get(url, params={
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "daily": "temperature_2m_max", "timezone": "auto"}, timeout=30)
    r.raise_for_status()
    d = r.json().get("daily", {})
    return dict(zip(d.get("time", []), d.get("temperature_2m_max", [])))


def city_pairs(args):
    """(forecast, actual) pairs for one city over the window."""
    city, (lat, lon), start, end = args
    try:
        actual = _series(ARCHIVE, lat, lon, start, end)
        fc = _series(HISTFC, lat, lon, start, end)
    except Exception:
        return []
    return [(f, actual[dt]) for dt, f in fc.items()
            if actual.get(dt) is not None and f is not None]


def brier_at(pairs, sigma):
    """Mean Brier over every (forecast, actual, bucket-near-forecast) using the
    CANONICAL bucket rule at the given sigma."""
    we.MEMBER_SIGMA = sigma
    tot, n = 0.0, 0
    for f, a in pairs:
        for T in range(round(f) - 5, round(f) + 6):
            p = bucket_probability([f], _parsed(T))
            h = 1 if resolves_yes(_parsed(T), a) else 0
            tot += (p - h) ** 2
            n += 1
    return tot / n if n else None


def main():
    saved = we.MEMBER_SIGMA
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=DAYS)
    s, e = start.isoformat(), end.isoformat()
    args = [(c, coord, s, e) for c, coord in STATIONS.items()]
    print(f"Backtesting {len(args)} cities over {DAYS} days ({s} -> {e})…\n")

    pairs = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for pr in ex.map(city_pairs, args):
            pairs.extend(pr)
    if not pairs:
        print("no data"); return

    # sigma sweep — the best-calibrated value. If it's far from 1.2, the live
    # per-member application is mis-tuned (the double-count question).
    print(f"{'sigma':>6}{'Brier':>10}")
    best = None
    for s10 in range(6, 31):
        sig = s10 / 10
        br = brier_at(pairs, sig)
        if best is None or br < best[1]:
            best = (sig, br); mark = "  <-- best"
        else:
            mark = ""
        print(f"{sig:>6.1f}{br:>10.4f}{mark}")

    # calibration table at the best sigma
    we.MEMBER_SIGMA = best[0]
    recs = []
    for f, a in pairs:
        for T in range(round(f) - 5, round(f) + 6):
            recs.append((bucket_probability([f], _parsed(T)),
                         1 if resolves_yes(_parsed(T), a) else 0))
    print(f"\nBest sigma = {best[0]:.1f} (Brier {best[1]:.4f}); live uses {saved}.")
    print(f"\n{'band':<10}{'predicted':>12}{'actual':>10}{'n':>8}")
    for lo, hi in [(0, .1), (.1, .2), (.2, .3), (.3, .5), (.5, 1.01)]:
        b = [(p, h) for p, h in recs if lo <= p < hi]
        if not b:
            continue
        ap = sum(p for p, _ in b) / len(b); ac = sum(h for _, h in b) / len(b)
        flag = "  ok" if abs(ap - ac) < 0.05 else "  <-- off"
        print(f"{int(lo*100)}-{int(hi*100)}%{'':<4}{ap*100:>10.1f}%{ac*100:>9.1f}%{len(b):>8}{flag}")
    print(f"\n{len(recs):,} city-day-bucket predictions. Calibrated = predicted≈actual in every band.")
    we.MEMBER_SIGMA = saved


if __name__ == "__main__":
    main()
