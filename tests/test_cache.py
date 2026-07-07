"""Guards the weather/ensemble fetch cache against the stale-coverage bug.

Old behaviour: the fetch cache returned its blob for 30 min regardless of which
cities were asked for. So when a new day's markets (new cities) appeared, or a
market's settlement station resolved to different coords, those cities silently
got stale/missing data -> model_prob None -> never actionable. The fix keys the
cache by a signature of the requested (city, unit, station) set and invalidates
when that set changes, not only on TTL.

Run: venv/bin/python -m tests.test_cache   (from repo root)
"""
from strategies.weather_edge import _cache_sig, _cache_fresh

CASES = []


def check(name, cond):
    CASES.append((name, bool(cond)))


# ---- signature reflects exactly what was requested ----
s_lon_par = _cache_sig({"London": "C", "Paris": "C"})
s_par_lon = _cache_sig({"Paris": "C", "London": "C"})
s_lon = _cache_sig({"London": "C"})
check("signature is order-independent", s_lon_par == s_par_lon)
check("signature changes when a city is added/removed", s_lon_par != s_lon)
check("signature changes when a city's unit changes (C->F)",
      _cache_sig({"London": "C"}) != _cache_sig({"London": "F"}))

# ---- freshness gate: fresh ONLY if non-empty AND same sig AND within TTL ----
check("empty cache is never fresh",
      _cache_fresh({}, s_lon, 100.0, s_lon, 200.0, 1800) is False)
check("same sig within TTL is fresh",
      _cache_fresh({"x": 1}, s_lon, 100.0, s_lon, 200.0, 1800) is True)
check("expired (beyond TTL) is not fresh",
      _cache_fresh({"x": 1}, s_lon, 100.0, s_lon, 2000.0, 1800) is False)
check("THE BUG: changed city-set is not fresh even within TTL",
      _cache_fresh({"x": 1}, s_lon, 100.0, s_lon_par, 200.0, 1800) is False)


if __name__ == "__main__":
    fails = [n for n, ok in CASES if not ok]
    for n, ok in CASES:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"\n{len(CASES)-len(fails)}/{len(CASES)} passed")
    raise SystemExit(1 if fails else 0)
