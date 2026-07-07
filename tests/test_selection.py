"""Guards the pure selection rule (is_actionable), the raised liquidity floor,
the cheap-tail tag, and the ensemble model ids.

Run: venv/bin/python -m tests.test_selection
"""
import config
from strategies import weather_edge as we
from strategies.weather_edge import (is_actionable, bet_features, VOLUME_FLOOR,
                                      TAIL_MAX_PRICE, VALID_ENSEMBLE_MODELS,
                                      reset_data_status, ensemble_rate_limited,
                                      ometeo_endpoint)

CASES = []


def check(name, cond):
    CASES.append((name, bool(cond)))


def cand(**kw):
    base = {"edge": 0.15, "model_prob": 0.7, "liquid": True, "volume": 5000,
            "lead": 1, "side_price": 0.12, "maker_fits": True,
            "station_confirmed": True, "is_exact": False, "side": "YES"}
    base.update(kw)
    return base


# ---- a healthy candidate is actionable ----
check("healthy candidate is actionable", is_actionable(cand()) is True)

# ---- liquidity floor (bug #10): below VOLUME_FLOOR is rejected ----
check("below volume floor rejected", is_actionable(cand(volume=VOLUME_FLOOR - 1)) is False)
check("at volume floor accepted", is_actionable(cand(volume=VOLUME_FLOOR)) is True)
check("volume floor was raised above the old 250", VOLUME_FLOOR >= 1000)

# ---- edge thresholds ----
check("edge below threshold rejected", is_actionable(cand(edge=0.05)) is False)
check("edge above sanity cap rejected (stale price)", is_actionable(cand(edge=0.50)) is False)

# ---- dead-zone: a 0.40-0.60 priced side is skipped ----
check("dead-zone price rejected", is_actionable(cand(side_price=0.50)) is False)
check("cheap side accepted", is_actionable(cand(side_price=0.12)) is True)

# ---- lead time & data presence ----
check("too-far lead rejected", is_actionable(cand(lead=9)) is False)
check("no model_prob rejected", is_actionable(cand(model_prob=None)) is False)
check("illiquid rejected", is_actionable(cand(liquid=False)) is False)
check("non-maker-fit rejected", is_actionable(cand(maker_fits=False)) is False)

# ---- learned-loser veto still works through the pure rule ----
check("avoided category rejected", is_actionable(cand(station_confirmed=False),
      avoid={"unconfirmed_station"}) is False)

# ---- cheap-tail tag (bug #11) ----
check("cheap tail tagged when price <= TAIL_MAX_PRICE",
      "cheap_tail" in bet_features({"side_price": TAIL_MAX_PRICE, "side": "YES"}))
check("not tagged cheap when price above threshold",
      "not_tail" in bet_features({"side_price": 0.30, "side": "YES"}))
check("no tail tag when price unknown",
      not ({"cheap_tail", "not_tail"} & bet_features({"side": "YES"})))

# ---- ensemble model ids are all VALID (guards the icon_global typo class) ----
configured = we.ENSEMBLE_MODELS.split(",")
check("every configured ensemble model id is valid",
      all(m in VALID_ENSEMBLE_MODELS for m in configured))
check("at least one ensemble model configured", len(configured) >= 1)

# ---- data-status flag (honest 'rate limited' vs 'no edge') ----
reset_data_status()
check("data status resets to not-rate-limited", ensemble_rate_limited() is False)

# ---- paid-API-key endpoint swap (removes the free daily cap -> runs constantly) ----
_saved_key = config.OPENMETEO_API_KEY
config.OPENMETEO_API_KEY = ""
u, extra = ometeo_endpoint("https://ensemble-api.open-meteo.com/v1/ensemble")
check("no key -> free URL unchanged", u == "https://ensemble-api.open-meteo.com/v1/ensemble")
check("no key -> no extra params", extra == {})
config.OPENMETEO_API_KEY = "TESTKEY123"
u2, e2 = ometeo_endpoint("https://ensemble-api.open-meteo.com/v1/ensemble")
check("with key -> uncapped customer host", u2 == "https://customer-ensemble-api.open-meteo.com/v1/ensemble")
check("with key -> apikey attached", e2 == {"apikey": "TESTKEY123"})
u3, _ = ometeo_endpoint("https://api.open-meteo.com/v1/forecast")
check("with key -> forecast host swapped too", u3 == "https://customer-api.open-meteo.com/v1/forecast")
config.OPENMETEO_API_KEY = _saved_key   # restore


if __name__ == "__main__":
    fails = [n for n, ok in CASES if not ok]
    for n, ok in CASES:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"\n{len(CASES)-len(fails)}/{len(CASES)} passed")
    raise SystemExit(1 if fails else 0)
