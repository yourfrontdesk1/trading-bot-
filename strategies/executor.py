"""Order executor — turns actionable weather-edge rows into maker BUY orders.

HARD-GATED and safe by default. Every order goes through
brokers.polymarket_clob.place_maker_bet, which places NOTHING unless the bot is
deliberately armed (DRY_RUN=false AND a wallet key AND py-clob-client installed).
In the default DRY_RUN state this logs the exact order it WOULD rest and places
nothing — so the bot visibly "makes its own bets" with the safety catch on.

Dedupe: one order per market+date+side, tracked in state/orders.jsonl, so a
3-minute rescan never double-places the same bet.
"""
import os
import json

from brokers import polymarket_clob

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")
ORDERS = os.path.join(STATE_DIR, "orders.jsonl")


def _key(r):
    return f"{r.get('question')}|{r.get('market_date')}|{r.get('best_side')}"


def _placed_keys(path):
    keys = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    keys.add(json.loads(line)["key"])
                except Exception:
                    continue
    return keys


def place_actionable(rows, ts, path=ORDERS):
    """Submit a maker BUY for every actionable row we haven't ordered yet.

    ts: ISO timestamp string (this module can't read the clock). Returns a summary
    dict. Places real orders ONLY if polymarket_clob reports it's armed; otherwise
    logs intents. `path` is injectable for tests."""
    os.makedirs(STATE_DIR, exist_ok=True)
    already = _placed_keys(path)
    attempted = live = intents = skipped = 0
    with open(path, "a") as f:
        for r in rows:
            if not r.get("actionable"):
                continue
            k = _key(r)
            if k in already:
                skipped += 1
                continue
            tid, price, dollars = r.get("token_id"), r.get("p_market"), r.get("bet_usd")
            if not tid or not price or not dollars:
                continue  # can't rest an order without a token id / price / size
            attempted += 1
            res = polymarket_clob.place_maker_bet(tid, price, dollars)
            if res.get("placed"):
                live += 1
            else:
                intents += 1
            f.write(json.dumps({
                "key": k, "ts": ts, "question": r.get("question"),
                "side": r.get("best_side"), "price": price, "dollars": dollars,
                "shares": res.get("shares"), "placed": bool(res.get("placed")),
                "reason": res.get("reason"), "armed": bool(res.get("placed")),
            }) + "\n")
            already.add(k)
    return {"attempted": attempted, "placed_live": live,
            "logged_intents": intents, "skipped_existing": skipped,
            "armed": polymarket_clob._armed()}
