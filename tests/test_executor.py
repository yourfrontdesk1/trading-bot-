"""The bot placing its OWN bets — safely.

In the default DRY_RUN state the executor must: submit an intent for every
actionable row, place NOTHING real, skip non-actionable rows, and never
double-place the same market+date+side on a rescan.

Run: venv/bin/python -m tests.test_executor
"""
import os
import json
import tempfile

import config
from strategies import executor

CASES = []


def check(name, cond):
    CASES.append((name, bool(cond)))


def row(actionable=True, side="YES", token="TOK1", price=0.20, bet=1.25,
        q="Will the highest temperature in Paris be 35°C on July 7?", md="2026-07-07"):
    return {"actionable": actionable, "best_side": side, "token_id": token,
            "p_market": price, "bet_usd": bet, "question": q, "market_date": md}


tmp = os.path.join(tempfile.mkdtemp(), "orders.jsonl")

# safety precondition: the suite must run with the shipped safe default
check("DRY_RUN is on (test runs in safe mode)", config.DRY_RUN is True)

rows = [row(), row(actionable=False, q="skip me"), row(side="NO", token="TOK2", q="Another market?")]
s1 = executor.place_actionable(rows, "2026-07-06T12:00:00", path=tmp)
check("attempted only the 2 actionable rows", s1["attempted"] == 2)
check("placed ZERO real orders in dry-run", s1["placed_live"] == 0)
check("logged 2 intents", s1["logged_intents"] == 2)
check("reports not armed", s1["armed"] is False)

# the order log recorded intents, placed=False, with correct shares (dollars/price)
lines = [json.loads(l) for l in open(tmp)]
check("2 order lines written", len(lines) == 2)
check("every logged order placed=False", all(l["placed"] is False for l in lines))
check("shares computed = round(dollars/price,2)", abs(lines[0]["shares"] - round(1.25 / 0.20, 2)) < 1e-9)

# rescan with the SAME rows must not double-place
s2 = executor.place_actionable(rows, "2026-07-06T12:03:00", path=tmp)
check("rescan attempts nothing new", s2["attempted"] == 0)
check("rescan skips the 2 already-ordered", s2["skipped_existing"] == 2)
check("no extra lines appended on rescan", len(open(tmp).readlines()) == 2)

# a row missing a token id can't be ordered (no crash, just skipped)
s3 = executor.place_actionable([row(token=None, q="no token market?")], "2026-07-06T12:04:00", path=tmp)
check("row without token_id is not attempted", s3["attempted"] == 0)


if __name__ == "__main__":
    fails = [n for n, ok in CASES if not ok]
    for n, ok in CASES:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"\n{len(CASES)-len(fails)}/{len(CASES)} passed")
    raise SystemExit(1 if fails else 0)
