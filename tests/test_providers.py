"""The multi-provider blend: drop failed sources, keep the survivors as ensemble
members, and never crash when a provider returns None. Network calls aren't made
here — we test the pure combine/blend logic with stubbed provider results.

Run: venv/bin/python -m tests.test_providers
"""
from strategies.providers import combine, multi_forecast
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


if __name__ == "__main__":
    fails = [n for n, ok in CASES if not ok]
    for n, ok in CASES:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"\n{len(CASES)-len(fails)}/{len(CASES)} passed")
    raise SystemExit(1 if fails else 0)
