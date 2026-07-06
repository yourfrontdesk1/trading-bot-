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


def resolve_pending(today_iso):
    """Self-learning core: for every logged bet whose date has passed, fetch the
    ACTUAL temperature that occurred and record win/loss. This turns the paper
    ledger into a real, growing track record with zero human input.

    today_iso: 'YYYY-MM-DD' (module can't read the clock itself)."""
    import requests
    from strategies.weather_edge import (parse_question, station_for, _ometeo_unit,
                                          FORECAST_API)
    if not os.path.exists(LEDGER):
        return 0
    rows = []
    with open(LEDGER) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    resolved = 0
    for r in rows:
        if r.get("resolved") or not r.get("market_date"):
            continue
        if r["market_date"] >= today_iso:   # not settled yet
            continue
        parsed = parse_question(r.get("question", ""))
        loc = station_for(r.get("city", ""))
        if not parsed or not loc:
            continue
        lat, lon, _ = loc
        is_low = parsed["kind"] == "lowest"
        var = "temperature_2m_min" if is_low else "temperature_2m_max"
        try:
            resp = requests.get(FORECAST_API, params={
                "latitude": lat, "longitude": lon, "daily": var,
                "start_date": r["market_date"], "end_date": r["market_date"],
                "timezone": "auto", "temperature_unit": _ometeo_unit(parsed.get("unit", "C")),
            }, timeout=15)
            resp.raise_for_status()
            vals = resp.json().get("daily", {}).get(var, [])
            actual = vals[0] if vals else None
        except Exception:
            continue
        if actual is None:
            continue
        T = parsed["threshold_c"]
        if parsed["or_higher"]:
            yes = actual >= T
        elif parsed["or_below"]:
            yes = actual <= T + 0.99
        else:
            yes = T <= actual < T + 1
        outcome_side = "YES" if yes else "NO"
        r["resolved"] = True
        r["actual_temp"] = round(actual, 1)
        r["won"] = (r.get("side") == outcome_side)
        resolved += 1
    if resolved:
        with open(LEDGER, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return resolved


def calibration():
    """How well-calibrated are we? Compare predicted win-prob to actual outcomes.
    Returns a learning summary the model uses to self-correct."""
    if not os.path.exists(LEDGER):
        return {"resolved": 0, "brier": None, "buckets": []}
    rows = []
    with open(LEDGER) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    res = [r for r in rows if r.get("resolved") and r.get("model_prob") is not None]
    if not res:
        return {"resolved": 0, "brier": None, "buckets": []}
    # Brier score: mean( (predicted_win_prob - won)^2 ); lower is better
    def pwin(r):
        p = r["model_prob"]
        return p if r.get("side") == "YES" else 1 - p
    brier = sum((pwin(r) - (1 if r["won"] else 0)) ** 2 for r in res) / len(res)
    # calibration buckets: predicted band vs actual hit-rate
    bands = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    buckets = []
    for lo, hi in bands:
        b = [r for r in res if lo <= pwin(r) < hi]
        if b:
            buckets.append({"band": f"{int(lo*100)}-{int(hi*100)}%",
                            "predicted": round(sum(pwin(r) for r in b) / len(b) * 100),
                            "actual": round(sum(1 for r in b if r["won"]) / len(b) * 100),
                            "n": len(b)})
    return {"resolved": len(res), "brier": round(brier, 3), "buckets": buckets}


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
