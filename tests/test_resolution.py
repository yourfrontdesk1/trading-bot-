"""Correctness tests for the weather-market resolution / bucket rule.

The single most important invariant in this whole system: the rule the MODEL
uses to compute P(win) must be the SAME rule the LEDGER uses to score whether a
bet actually won. If they disagree, every calibration/Brier/win-rate number is
measuring the wrong thing — and those numbers are the entire deliverable.

Ground truth: Wunderground reports the daily high/low as a ROUNDED integer and
the market resolves to the range containing it. So for an observed temp `t`:
  "be T"          wins iff round(t) == T   <=>  T-0.5 <= t <  T+0.5
  "be T or higher"wins iff round(t) >= T   <=>       t >= T-0.5
  "be T or below" wins iff round(t) <= T   <=>       t <  T+0.5

Run: venv/bin/python -m tests.test_resolution   (from repo root)
"""
from strategies.weather_edge import resolves_yes, bucket_hits, bucket_probability


def _p(kind="highest", T=22, or_higher=False, or_below=False, unit="C"):
    return {"kind": kind, "city": "Testville", "threshold_c": T, "unit": unit,
            "or_higher": or_higher, "or_below": or_below, "date_str": "July 7"}


CASES = []


def check(name, cond):
    CASES.append((name, bool(cond)))


# ---- exact "be T" : half-open [T-0.5, T+0.5), matching round-half-up ----
p = _p(T=22)
check("exact 22.0 -> YES", resolves_yes(p, 22.0) is True)
check("exact 22.4 -> YES", resolves_yes(p, 22.4) is True)
check("exact 22.49 -> YES", resolves_yes(p, 22.49) is True)
check("exact 22.5 -> NO (rounds to 23)", resolves_yes(p, 22.5) is False)
check("exact 22.7 -> NO (rounds to 23)", resolves_yes(p, 22.7) is False)
check("exact 21.5 -> YES (rounds to 22)", resolves_yes(p, 21.5) is True)
check("exact 21.49 -> NO (rounds to 21)", resolves_yes(p, 21.49) is False)
# THE regression the old ledger got wrong: actual 22.7 rounds to 23, so an
# 'exactly 22' market must resolve NO — the old `T <= actual < T+1` said YES.
check("REGRESSION exact 22 @ actual 22.7 is NOT a YES", not resolves_yes(p, 22.7))

# ---- "be T or higher" : t >= T-0.5 ----
ph = _p(T=30, or_higher=True)
check("or_higher 30 @ 29.6 -> YES (rounds 30)", resolves_yes(ph, 29.6) is True)
check("or_higher 30 @ 29.5 -> YES (rounds 30)", resolves_yes(ph, 29.5) is True)
check("or_higher 30 @ 29.49 -> NO (rounds 29)", resolves_yes(ph, 29.49) is False)
check("or_higher 30 @ 35.0 -> YES", resolves_yes(ph, 35.0) is True)

# ---- "be T or below" : t < T+0.5 ----
pb = _p(T=10, or_below=True)
check("or_below 10 @ 10.4 -> YES (rounds 10)", resolves_yes(pb, 10.4) is True)
check("or_below 10 @ 10.49 -> YES (rounds 10)", resolves_yes(pb, 10.49) is True)
check("or_below 10 @ 10.5 -> NO (rounds 11)", resolves_yes(pb, 10.5) is False)
check("or_below 10 @ 5.0 -> YES", resolves_yes(pb, 5.0) is True)

# ---- bucket_hits must be defined by the SAME predicate ----
members = [20.0, 21.6, 22.0, 22.3, 22.8, 23.1]
expect = sum(1 for m in members if resolves_yes(p, m))
check("bucket_hits == count of resolves_yes", bucket_hits(members, p) == expect)

# ---- bucket_probability is bounded and points the right way ----
prob_on = bucket_probability([22.0, 22.1, 21.9], p)      # centred on the bucket
prob_off = bucket_probability([40.0, 41.0, 39.0], p)     # miles away
check("prob centred-on-bucket > prob far-away", prob_on > prob_off)
check("prob in (0,1)", 0.0 < prob_on < 1.0 and 0.0 < prob_off < 1.0)

# ---- coherence: for an open-ended (or_higher) market, members deep on the YES
# side give BOTH a high P(YES) and each resolves YES ----
deep_h = _p(T=22, or_higher=True)
deep = [30.0, 30.0, 30.0]
check("deep or_higher P high", bucket_probability(deep, deep_h) > 0.95)
check("deep or_higher all resolve YES", all(resolves_yes(deep_h, m) for m in deep))

# ---- documented ceiling: an EXACT 1°-wide bucket can't exceed ~0.35 even dead
# centre at sigma=1.2 (member noise is wider than the bucket). This is intended,
# not a bug — it's why the strategy prefers open-ended tails over exact buckets. ----
centre = bucket_probability([22.0, 22.0, 22.0], p)
check("exact-bucket ceiling is modest (0.25-0.35)", 0.25 < centre < 0.35)


if __name__ == "__main__":
    fails = [n for n, ok in CASES if not ok]
    for n, ok in CASES:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"\n{len(CASES)-len(fails)}/{len(CASES)} passed")
    raise SystemExit(1 if fails else 0)
