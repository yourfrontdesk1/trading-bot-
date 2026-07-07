# LESSONS — mistakes found, fixed, and guarded

The rule: **remember every mistake, never make it twice.** Each entry below is a
real bug that shipped, its root cause, the fix, and the regression test that now
makes it impossible to reintroduce silently. Add to this file every time a bug is
found — before or instead of moving on.

Run all guards: `venv/bin/python -m tests.run_all`

---

## The one invariant everything depends on

The number this whole project exists to produce is an **honest paper track record**
(win rate + calibration) that proves an edge *before* real money. That number is
only meaningful if **the rule the model uses to price a bet is byte-for-byte the
same rule used to (a) settle it and (b) calibrate sigma.** Any drift between those
three = the track record measures noise. Every bug below was a form of that drift.

Canonical rule lives in ONE place: `weather_edge.resolves_yes(parsed, temp)`.
Wunderground rounds the daily high/low to an integer and the market resolves to
the range containing it, so for observed temp `t` and threshold `T`:

| market form   | wins iff        | interval            |
|---------------|-----------------|---------------------|
| "be T"        | round(t) == T   | `T-0.5 <= t < T+0.5`|
| "be T or higher"| round(t) >= T | `t >= T-0.5`        |
| "be T or below"| round(t) <= T  | `t <  T+0.5`        |

---

## Bug #1 — model vs ledger settlement drift  (CRITICAL)
- **Symptom:** win-rate / Brier would look plausible but be wrong; no crash.
- **Root cause:** `bucket_probability` priced the `[T-0.5, T+0.5)` bucket, but
  `ledger.resolve_pending` scored wins on offset intervals (`T <= actual < T+1`,
  `actual >= T`, `actual <= T+0.99`) — every branch ~0.5°C off. A bet on NO that
  truly won could be logged as a loss.
- **Fix:** extracted `resolves_yes()` as the single source of truth; `bucket_hits`
  and the ledger both route through it.
- **Guard:** `tests/test_resolution.py` (incl. the `REGRESSION exact 22 @ 22.7` case).

## Bug #2 — resolver used the wrong data source
- **Symptom:** bets older than ~92 days never resolved (track record silently
  stalls); recent resolutions could disagree with the calibration basis by >1°C.
- **Root cause:** `resolve_pending` fetched actuals from the **forecast** API,
  which returns nothing beyond ~92 days and whose past values differ from ERA5.
  But `calibrate_sigma` fit sigma against **ERA5 archive** actuals — so the grader
  used a different yardstick than the tuner.
- **Fix:** `ledger.fetch_actual_temp()` queries the **ERA5 archive** first (any past
  date, same source as calibration), forecast API only as a recent-days fallback.
- **Guard:** verified empirically (90-days-ago now resolves; archive vs forecast
  gap documented). See `ARCHIVE_API` note in `weather_edge.py`.

## Bug #3 — calibrate lied about the current value + banker's rounding
- **Symptom:** running `calibrate_sigma` printed `MEMBER_SIGMA = 0.6` while the
  code used `1.2`; outcomes graded with Python `round()` (banker's: `round(22.5)==22`)
  instead of round-half-up.
- **Fix:** print the live `MEMBER_SIGMA`; grade outcomes with the same
  `T-0.5 <= a < T+0.5` half-open rule as settlement.

## Near-miss #6 — wrong Open-Meteo model id (caught by verifying, not assuming)
- **What almost happened:** adding ICON to the ensemble, the obvious id `icon_global`
  is **wrong** — Open-Meteo's real id is `icon_global_eps`. A wrong id returns 400
  and silently drops that whole model from every city's forecast, with no error.
- **How it was caught:** verified the id against the Open-Meteo docs before shipping,
  instead of trusting memory.
- **Guard:** `VALID_ENSEMBLE_MODELS` + `test_selection` assert every configured id is
  valid. Blend is now GFS(31)+ECMWF(51)+ICON(40) = 122 members.

## Research-driven tuning (benchmarked vs winning weather traders)
- `VOLUME_FLOOR` 250 -> 1000: measured Polymarket temp markets split into a liquid
  cluster >=$5k and thin junk <$1k; $1k cuts stale-price artifacts. (The pros' $10k
  floor is Kalshi-scale — Polymarket temp markets top out ~$10k.)
- `TAIL_MAX_PRICE`/`cheap_tail`: the top ROI traders (e.g. one at 4% win-rate over
  10,825 trades, still +41%) concentrate on cheap tails (<=~$0.15) — low hit-rate,
  big payouts, +EV at volume. We tag, prioritise, and feed it to `lessons()`.
- Selection logic extracted to the pure, tested `is_actionable()` (was a 10-line
  inline boolean). Guard: `test_selection`.

## Bug #5 — year-rollover blindness in market-date parsing
- **Symptom:** across the New Year, near-term markets vanish — a 'January 2'
  market seen on Dec 30 resolved to *this-year* January (~360 days past) and was
  dropped as stale.
- **Fix:** `resolve_market_date(date_str, today)` picks the year (this/next/prev)
  nearest today; `build_edge_table` uses it instead of a fixed current-year.
- **Guard:** `tests/test_dates.py`.

## Bug #4 — stale-cache coverage gap
- **Symptom:** a new day's markets (new cities) could be invisible for up to 30
  min — `model_prob` None, never actionable — with no error.
- **Root cause:** `fetch_weather` / `fetch_ensemble` returned their cached blob on
  TTL alone, ignoring *which* cities were requested.
- **Fix:** `_cache_sig(units)` signs the requested (city, unit, station) set;
  `_cache_fresh(...)` requires a signature match AND non-empty AND within TTL.
- **Guard:** `tests/test_cache.py`.

---

## Self-learning: the bot remembers its own losing bets (`ledger.lessons`)
The point of the ledger is not just a scoreboard — the bot must *diagnose* which
kinds of bet lose and stop making them.
- `weather_edge.bet_features(feat)` tags every bet by category (station confirmed?,
  exact vs open-ended bucket, lead 0-1 vs 2+, side, edge size). The SAME tags are
  computed for resolved bets and for live candidates, so what's learned is what's
  enforced.
- `ledger.lessons()` groups resolved bets by tag and flags a category to `avoid`
  only when its win-rate trails BOTH the model's expectation (>10pts) AND the whole
  book (>5pts), over `>= min_n` (20) resolved bets.
- `build_edge_table(avoid=…)` refuses to mark those categories actionable;
  `webapp` feeds `lessons().avoid` in on every scan. Blocked rows carry `blocked_by`.
- **Sub-lesson learned while building it:** per-tag aggregation *confounds* — a
  losing bet blames every category it touches, smearing innocent co-occurring tags.
  Fixed by faulting a category only when it underperforms the *book*, isolating the
  discriminating axis. Guard: `tests/test_lessons.py` ("still accepts a healthy
  candidate"). Don't regress this into naive `gap < -0.10`.
- **Guardrail:** stays empty until `>= min_n` — never learn a lesson from noise.

## Component map (the whole Polymarket pipeline, end to end)

1. **`brokers/polymarket_client.py`** — read-only Gamma API client (markets + prices).
2. **`strategies/weather_edge.py`** — the engine:
   - `fetch_temp_markets` → pulls active temp markets, `parse_question` structures them.
   - `station_from_description` → resolves each market's real settlement airport
     (ICAO in its Wunderground URL) so forecasts match the settlement feed.
   - `fetch_ensemble` → 82-member GFS+ECMWF distribution per city/date.
   - `bucket_probability` → P(YES) = mean over members of Normal(member, sigma)
     mass in the bucket. `MEMBER_SIGMA=1.2` fitted by `calibrate_sigma.py`.
   - `price_edge` / `bet_size_usd` → maker-fee edge + quarter-Kelly size, capped.
   - `build_edge_table` → ranks actionable opportunities (edge, liquidity, lead,
     dead-zone, maker-fit filters).
   - `resolves_yes` → THE canonical settlement rule (see top).
3. **`strategies/ledger.py`** — paper CLV track record: `log_scan` appends new
   actionable bets; `resolve_pending` settles past ones via `fetch_actual_temp`
   (ERA5); `stats` / `calibration` report win-rate + Brier + reliability buckets;
   `lessons()` = the self-learning avoid-list.
4. **`strategies/executor.py`** — turns actionable rows into maker BUY orders via
   the hard-gated `polymarket_clob.place_maker_bet` (`weather_edge._token_ids`
   supplies the CLOB token). Dedupes to `state/orders.jsonl`. DRY_RUN => logs the
   intended order, places nothing. This is the "bot bets itself" path; going LIVE
   still needs Python>=3.9.10 + py-clob-client + a funded fresh wallet + DRY_RUN=false.
4. **`strategies/calibrate_sigma.py`** — offline: fits `MEMBER_SIGMA` by minimising
   Brier of archived-forecast-vs-ERA5 across real stations.
5. **`webapp/server.py`** — dashboard + `_autopilot` that refreshes markets, runs
   AI research, re-scans/settles, and calls the executor every 3h hands-off. Now
   an always-on launchd service (`~/Library/LaunchAgents/com.leon.tradingbot.plist`).

## Known residual risks (documented, not yet closed)
- **Data source ≠ official METAR.** ERA5/open-meteo can differ from the exact
  Wunderground station high by enough to flip a 1°-wide bucket. Mitigated by
  station resolution + `station_confirmed`, not eliminated.
- **Exact-degree buckets are inherently low-probability** (~0.32 ceiling at
  sigma 1.2) — the strategy should prefer open-ended tails. See `test_resolution`.
- **Real-money path still blocked:** Python 3.9.6 (< py-clob-client's 3.9.10),
  Gibraltar geo (trading permission unverified), no funded burner wallet. Prove
  the paper edge first (target 50–100 resolved bets).
