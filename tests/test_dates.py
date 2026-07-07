"""Market-date parsing must pick the right calendar YEAR.

Bug: parse_date always used the current year, so a 'January 2' market seen on
Dec 30 became this-year-January (long past) and was silently dropped as stale —
the bot goes blind to near-term markets across the New Year boundary.
resolve_market_date picks the year (this/next/prev) putting the date nearest today.

Run: venv/bin/python -m tests.test_dates
"""
from strategies.weather_edge import resolve_market_date

CASES = []


def check(name, cond):
    CASES.append((name, bool(cond)))


# normal near-term: July 8 seen on 2026-07-06 -> this year
check("normal near-term stays this year",
      resolve_market_date("July 8", "2026-07-06") == "2026-07-08")

# THE BUG: January 2 seen on 2025-12-30 -> NEXT year, not this year
check("Jan market seen in late Dec rolls to next year",
      resolve_market_date("January 2", "2025-12-30") == "2026-01-02")

# mirror case: December 30 seen on 2026-01-02 -> PREVIOUS year (just settled)
check("Dec market seen in early Jan uses previous year",
      resolve_market_date("December 30", "2026-01-02") == "2025-12-30")

# a genuinely stale same-year date stays same year (so the stale filter drops it)
check("recent past stays same year (still stale)",
      resolve_market_date("July 4", "2026-07-06") == "2026-07-04")

# junk input -> None, no crash
check("unparseable date -> None", resolve_market_date("not a date", "2026-07-06") is None)
check("missing today -> None", resolve_market_date("July 8", "") is None)


if __name__ == "__main__":
    fails = [n for n, ok in CASES if not ok]
    for n, ok in CASES:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"\n{len(CASES)-len(fails)}/{len(CASES)} passed")
    raise SystemExit(1 if fails else 0)
