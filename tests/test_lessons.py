"""The bot's mistake-memory: it must LEARN which categories of bet lose and then
REFUSE to repeat them — but only once it has real evidence, never from noise.

Run: venv/bin/python -m tests.test_lessons   (from repo root)
"""
from strategies.weather_edge import bet_features, passes_lessons
from strategies import ledger

CASES = []


def check(name, cond):
    CASES.append((name, bool(cond)))


def row(won, station_confirmed, model_prob=0.7, side="YES", lead=1, edge=0.15,
        question="Will the highest temperature in Testville be 22°C on July 7?"):
    return {"resolved": True, "won": won, "model_prob": model_prob, "side": side,
            "station_confirmed": station_confirmed, "lead_days": lead, "edge": edge,
            "question": question}


# ---- feature tagging: one tag per axis, confirmed vs unconfirmed distinguished ----
f_unconf = {"station_confirmed": False, "is_exact": True, "lead_days": 1,
            "side": "YES", "edge": 0.15}
tags = bet_features(f_unconf)
check("tags include unconfirmed_station", "unconfirmed_station" in tags)
check("tags include exact_bucket", "exact_bucket" in tags)
check("tags include lead_0_1", "lead_0_1" in tags)
check("confirmed differs from unconfirmed",
      "confirmed_station" in bet_features({**f_unconf, "station_confirmed": True}))

# ---- LEARN: 30 unconfirmed-station bets the model expected ~70% to win but only
# 30% did (provably overconfident); 30 confirmed-station bets that met expectation.
unconf = [row(won=(i < 9), station_confirmed=False) for i in range(30)]   # 9/30 = 30% won
conf = [row(won=(i < 21), station_confirmed=True) for i in range(30)]     # 21/30 = 70% won
L = ledger.lessons(rows=unconf + conf, min_n=20)
check("engine flags unconfirmed_station as avoid", "unconfirmed_station" in L["avoid"])
check("engine does NOT flag confirmed_station", "confirmed_station" not in L["avoid"])

# ---- NO learning from noise: same skew but below min_n -> nothing avoided ----
small = [row(won=(i < 1), station_confirmed=False) for i in range(5)]
Ls = ledger.lessons(rows=small, min_n=20)
check("below min_n yields empty avoid (no noise-learning)", Ls["avoid"] == [])

# ---- FEED BACK: the selector must reject a live candidate in the learned category
avoid = L["avoid"]
bad = {"station_confirmed": False, "is_exact": True, "lead_days": 1, "side": "YES", "edge": 0.15}
good = {"station_confirmed": True, "is_exact": False, "lead_days": 1, "side": "YES", "edge": 0.15}
check("selector rejects a learned-loser candidate", passes_lessons(bad, avoid) is False)
check("selector still accepts a healthy candidate", passes_lessons(good, avoid) is True)
check("empty lessons never block anything", passes_lessons(bad, []) is True)


if __name__ == "__main__":
    fails = [n for n, ok in CASES if not ok]
    for n, ok in CASES:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"\n{len(CASES)-len(fails)}/{len(CASES)} passed")
    raise SystemExit(1 if fails else 0)
