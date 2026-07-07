"""Latency-arb scan timing: the bot should wake right after fresh model data lands
(≈05/11/17/23 UTC), not on a dumb fixed timer into stale prices.

Run: venv/bin/python -m tests.test_schedule
"""
from datetime import datetime
from strategies.weather_edge import seconds_until_next_release, MODEL_RELEASE_UTC_HOURS

CASES = []


def check(name, cond):
    CASES.append((name, bool(cond)))


def at(h, m=0, s=0):
    return datetime(2026, 7, 8, h, m, s)


H = 3600
# just before the 05:00 window -> ~1h away
check("04:00 -> next release in 1h", seconds_until_next_release(at(4)) == 1 * H)
# just after 05:00 -> next is 11:00, 6h away
check("05:30 -> next release in 5.5h", seconds_until_next_release(at(5, 30)) == int(5.5 * H))
# midday between windows
check("12:00 -> next release 17:00 (5h)", seconds_until_next_release(at(12)) == 5 * H)
# after the last window -> wraps to 05:00 tomorrow
check("23:30 -> wraps to 05:00 tomorrow (5.5h)", seconds_until_next_release(at(23, 30)) == int(5.5 * H))
check("00:00 -> first window 05:00 (5h)", seconds_until_next_release(at(0)) == 5 * H)

# never returns non-positive or absurd values across the whole day
ok = all(0 < seconds_until_next_release(at(h, mm)) <= 6 * H
         for h in range(24) for mm in (0, 30))
check("always in (0, 6h] for every half-hour of the day", ok)
check("four release windows configured", len(MODEL_RELEASE_UTC_HOURS) == 4)


if __name__ == "__main__":
    fails = [n for n, ok in CASES if not ok]
    for n, ok in CASES:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"\n{len(CASES)-len(fails)}/{len(CASES)} passed")
    raise SystemExit(1 if fails else 0)
