"""The multi-provider blend: drop failed sources, keep the survivors as ensemble
members, and never crash when a provider returns None. Network calls aren't made
here — we test the pure combine/blend logic with stubbed provider results.

Run: venv/bin/python -m tests.test_providers
"""
from datetime import datetime, timezone
from strategies.providers import combine, multi_forecast, _daily_from_metar, metar_daily
from strategies.weather_edge import bucket_probability

CASES = []


def check(name, cond):
    CASES.append((name, bool(cond)))


# ---- combine drops None (failed providers) and keeps real forecasts ----
check("combine drops Nones", combine([22.0, None, 23.5, None]) == [22.0, 23.5])
check("all-failed -> empty list", combine([None, None]) == [])
check("all-good -> all kept", combine([20.0, 21.0]) == [20.0, 21.0])

# ---- multi_forecast with stub providers (no network) ----
def stub(val):
    return lambda lat, lon, d, is_low, unit: val

got = multi_forecast(51.5, -0.1, "2026-07-09", False, "C",
                     providers=(stub(22.4), stub(None), stub(23.1)))
check("multi_forecast blends the working providers", got == [22.4, 23.1])
check("multi_forecast survives all-fail", multi_forecast(0, 0, "2026-07-09", False, "C",
      providers=(stub(None),)) == [])

# ---- the blend feeds bucket_probability just like ensemble members do ----
p = {"kind": "highest", "threshold_c": 23, "or_higher": True, "or_below": False, "unit": "C"}
members = multi_forecast(51.5, -0.1, "2026-07-09", False, "C",
                         providers=(stub(24.0), stub(23.5)))
prob = bucket_probability(members, p)
check("blended members yield a valid probability", prob is not None and 0 < prob < 1)
check("two warm forecasts above threshold -> high P(YES)", prob > 0.6)


# ---- METAR settlement reader: daily high/low from station obs (the answer key) ----
def _ts(y, mo, d, h):
    return int(datetime(y, mo, d, h, tzinfo=timezone.utc).timestamp())

obs = [
    {"temp": 20, "obsTime": _ts(2026, 7, 7, 6)},
    {"temp": 28, "obsTime": _ts(2026, 7, 7, 14)},   # the day's high
    {"temp": 18, "obsTime": _ts(2026, 7, 7, 2)},    # the day's low
    {"temp": 40, "obsTime": _ts(2026, 7, 8, 14)},   # another day — must be ignored
    {"temp": None, "obsTime": _ts(2026, 7, 7, 10)},  # missing temp — skipped
]
check("METAR daily high = the day's max", _daily_from_metar(obs, "2026-07-07", False, "C") == 28)
check("METAR daily low = the day's min", _daily_from_metar(obs, "2026-07-07", True, "C") == 18)
check("METAR isolates the requested date", _daily_from_metar(obs, "2026-07-08", False, "C") == 40)
check("METAR °C→°F conversion (20C=68F)",
      abs(_daily_from_metar([{"temp": 20, "obsTime": _ts(2026, 7, 7, 12)}], "2026-07-07", False, "F") - 68.0) < 1e-6)
check("METAR no obs for date -> None", _daily_from_metar(obs, "2026-07-01", False, "C") is None)
check("metar_daily with no ICAO -> None (no crash)", metar_daily(None, "2026-07-07", False) is None)


if __name__ == "__main__":
    fails = [n for n, ok in CASES if not ok]
    for n, ok in CASES:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"\n{len(CASES)-len(fails)}/{len(CASES)} passed")
    raise SystemExit(1 if fails else 0)
