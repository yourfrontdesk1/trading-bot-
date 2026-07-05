"""Paper CLV ledger — the real deliverable for a £30 bankroll.

We are NOT trying to make money at this size; we are proving the model has a
genuine edge (positive closing-line value / good calibration) BEFORE risking a
penny. This logs every intended bet each scan so a track record accumulates.

Stored at state/bets.jsonl (gitignored). One JSON line per logged bet.
"""
import os
import json

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")
LEDGER = os.path.join(STATE_DIR, "bets.jsonl")


def _ensure():
    os.makedirs(STATE_DIR, exist_ok=True)


def _key(row):
    return f"{row.get('question')}|{row.get('market_date')}"


def log_scan(actionable_rows, ts):
    """Append any NEW actionable bets we haven't logged for this market+date yet.
    ts is an ISO timestamp string passed in (module can't call time itself here)."""
    _ensure()
    seen = set()
    if os.path.exists(LEDGER):
        with open(LEDGER) as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["key"])
                except Exception:
                    continue
    added = 0
    with open(LEDGER, "a") as f:
        for r in actionable_rows:
            k = _key(r)
            if k in seen:
                continue
            f.write(json.dumps({
                "key": k, "ts": ts, "question": r.get("question"),
                "city": r.get("city"), "market_date": r.get("market_date"),
                "side": r.get("best_side"), "entry_price": r.get("p_market"),
                "model_prob": r.get("model_prob"), "edge": r.get("edge"),
                "bet_usd": r.get("bet_usd"), "lead_days": r.get("lead_days"),
                "station_confirmed": r.get("station_confirmed"),
                "resolved": None, "won": None, "close_price": None,
            }) + "\n")
            seen.add(k)
            added += 1
    return added


def stats():
    """Summary of the paper track record so far."""
    if not os.path.exists(LEDGER):
        return {"logged": 0, "resolved": 0, "wins": 0, "win_rate": None,
                "avg_edge": None, "note": "No bets logged yet."}
    rows = []
    with open(LEDGER) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    resolved = [r for r in rows if r.get("resolved")]
    wins = [r for r in resolved if r.get("won")]
    edges = [r["edge"] for r in rows if r.get("edge") is not None]
    return {
        "logged": len(rows),
        "resolved": len(resolved),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(resolved) * 100, 1) if resolved else None,
        "avg_edge": round(sum(edges) / len(edges), 3) if edges else None,
        "note": "Log ~50-100 bets and prove a positive win rate vs entry price before funding.",
    }
