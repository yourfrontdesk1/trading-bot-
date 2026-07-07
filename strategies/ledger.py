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
                "station_icao": r.get("station_icao"),
                "resolved": None, "won": None, "close_price": None,
            }) + "\n")
            seen.add(k)
            added += 1
    return added


def fetch_actual_temp(lat, lon, var, unit, date_iso):
    """The observed daily high/low used to SETTLE a bet, or None.

    Tries the ERA5 archive first — it covers any past date and is the same source
    sigma was calibrated against — then falls back to the forecast API for the
    most recent days if the archive hasn't ingested them yet. Both queried in the
    market's native unit so the number matches the threshold's units."""
    import requests
    from strategies.weather_edge import (ARCHIVE_API, FORECAST_API, _ometeo_unit,
                                         ometeo_endpoint)
    for api in (ARCHIVE_API, FORECAST_API):
        try:
            url, extra = ometeo_endpoint(api)
            resp = requests.get(url, params={
                "latitude": lat, "longitude": lon, "daily": var,
                "start_date": date_iso, "end_date": date_iso,
                "timezone": "auto", "temperature_unit": _ometeo_unit(unit), **extra,
            }, timeout=20)
            resp.raise_for_status()
            vals = resp.json().get("daily", {}).get(var, [])
            actual = vals[0] if vals else None
            if actual is not None:
                return actual
        except Exception:
            continue
    return None


def resolve_pending(today_iso):
    """Self-learning core: for every logged bet whose date has passed, fetch the
    ACTUAL temperature that occurred and record win/loss. This turns the paper
    ledger into a real, growing track record with zero human input.

    today_iso: 'YYYY-MM-DD' (module can't read the clock itself)."""
    from strategies.weather_edge import (parse_question, station_for, resolves_yes)
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
        unit = parsed.get("unit", "C")
        # Settle on the ACTUAL station observation (METAR) the market pays out on —
        # the same source Wunderground uses. Fall back to ERA5 only if unavailable
        # (older than METAR's ~3-day window, or no ICAO on the bet).
        actual, settle_source = None, None
        icao = r.get("station_icao")
        if icao:
            from strategies.providers import metar_daily
            actual = metar_daily(icao, r["market_date"], is_low, unit)
            if actual is not None:
                settle_source = "metar"
        if actual is None:
            var = "temperature_2m_min" if is_low else "temperature_2m_max"
            actual = fetch_actual_temp(lat, lon, var, unit, r["market_date"])
            settle_source = "era5"
        if actual is None:
            continue
        # settle through the SAME canonical rule the model priced against, so the
        # win/loss we record matches the probability we predicted (no 0.5° drift).
        outcome_side = "YES" if resolves_yes(parsed, actual) else "NO"
        r["resolved"] = True
        r["actual_temp"] = round(actual, 1)
        r["settle_source"] = settle_source
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


def _feat_from_row(r):
    """Map a resolved ledger row to the feature dict bet_features expects."""
    from strategies.weather_edge import parse_question
    parsed = parse_question(r.get("question", "") or "")
    is_exact = (not parsed["or_higher"] and not parsed["or_below"]) if parsed else True
    return {"station_confirmed": bool(r.get("station_confirmed")), "is_exact": is_exact,
            "lead_days": r.get("lead_days"), "side": r.get("side"), "edge": r.get("edge"),
            "side_price": r.get("entry_price")}   # price paid -> cheap_tail axis


def lessons(rows=None, min_n=20):
    """The bot's memory of its own mistakes.

    Groups resolved bets by category (via weather_edge.bet_features) and, for each
    category with a real sample, compares the ACTUAL win-rate to what the model
    EXPECTED. A category where reality trails the model's own expectation by >10
    points over >= min_n bets is one the model is provably overconfident in — it
    goes on the `avoid` list, which build_edge_table() then refuses to act on.

    Crucially it stays EMPTY until a category has >= min_n resolved bets, so the
    bot never 'learns' a lesson from noise. Pass `rows` to test with synthetic data.
    """
    from collections import defaultdict
    from strategies.weather_edge import bet_features
    if rows is None:
        rows = [r for r in _load_rows()
                if r.get("resolved") and r.get("won") is not None
                and r.get("model_prob") is not None]
    agg = defaultdict(lambda: {"n": 0, "wins": 0, "exp": 0.0, "brier": 0.0})
    tot = {"n": 0, "wins": 0, "exp": 0.0}
    for r in rows:
        p = r.get("model_prob")
        if p is None:
            continue
        pwin = p if r.get("side") == "YES" else 1 - p   # model's predicted win prob
        won = 1 if r.get("won") else 0
        tot["n"] += 1; tot["wins"] += won; tot["exp"] += pwin
        for tag in bet_features(_feat_from_row(r)):
            a = agg[tag]
            a["n"] += 1; a["wins"] += won; a["exp"] += pwin; a["brier"] += (pwin - won) ** 2
    # baseline gap for the whole book: a model that's overconfident EVERYWHERE is a
    # calibration (sigma) problem, not a per-category lesson — so we only fault a
    # category that underperforms the book, isolating the truly discriminating axis.
    overall_gap = (tot["wins"] - tot["exp"]) / tot["n"] if tot["n"] else 0.0
    groups = []
    for tag, a in agg.items():
        if a["n"] < min_n:
            continue
        wr, exp = a["wins"] / a["n"], a["exp"] / a["n"]
        groups.append({"group": tag, "n": a["n"], "win_rate": round(wr, 3),
                       "expected": round(exp, 3), "gap": round(wr - exp, 3),
                       "brier": round(a["brier"] / a["n"], 3)})
    groups.sort(key=lambda g: g["gap"])   # worst (most overconfident) first
    # avoid = provably overconfident in absolute terms AND meaningfully worse than
    # the book (so co-occurring innocent tags aren't smeared with the real culprit).
    avoid = [g["group"] for g in groups
             if g["gap"] < -0.10 and g["gap"] < overall_gap - 0.05]
    return {"groups": groups, "avoid": avoid, "min_n": min_n,
            "overall_gap": round(overall_gap, 3),
            "note": ("A category is avoided when its win-rate trails BOTH the model's "
                     "expectation (>10pts) AND the whole book (>5pts) over >=%d resolved "
                     "bets. Empty until enough data — no learning from noise." % min_n)}


def _load_rows():
    rows = []
    if os.path.exists(LEDGER):
        with open(LEDGER) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return rows


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
