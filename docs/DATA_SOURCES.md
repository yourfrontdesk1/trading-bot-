# Weather Data Sources — the full catalog

Goal: feed the predictive model as many *independent, settlement-aligned* forecasts
as possible. Note the honest caveat at the bottom — most apps resell the same 2–3
underlying physical models, so raw *count* matters less than **independence** and
**matching the settlement source**.

## Tier 1 — wired in now (free, no key, no signup)
| Source | Coverage | Cap | Notes |
|---|---|---|---|
| **Open-Meteo** | Global | ~10k calls/day (free) | **Aggregates 30+ models** (ECMWF, GFS, ICON/DWD, Météo-France, JMA, UK Met Office, KMA, BOM…). Ensemble too. The daily cap is the only issue. |
| **Met.no** (MET Norway) | Global | none | No key/account. Hourly → daily high/low. |
| **NWS** (api.weather.gov) | US only | none | No key/account. Government service. |

## Tier 2 — free WITH a key (signup, no card) — each adds an independent member
| Source | Free allowance | Notes |
|---|---|---|
| **WeatherAPI.com** | ~1,000,000/month | Very generous; easiest big free tier. |
| **Visual Crossing** | ~1,000 records/day | Also the recommended Wunderground API replacement. |
| **OpenWeatherMap** | ~1,000/day | Ubiquitous. |
| **Tomorrow.io** | free tier | Modern API. |
| **Weatherbit** | free tier | — |

## Tier 3 — THE settlement source (highest value, hardest)
| Source | Notes |
|---|---|
| **Wunderground / Weather Company (IBM)** | **This is what the markets settle on.** Matching it beats any forecast. Went paid-only; no free API keys. Options: scrape the station history/forecast page (the market descriptions already link it), or a paid data package. Highest edge, most effort. |

## Tier 4 — raw model data (maximum power, maximum effort)
| Source | Notes |
|---|---|
| **NOAA NOMADS** | Raw GFS/GEFS ensemble GRIB files — free, but heavy engineering to download/decode. |
| **ECMWF Open Data** | Free open ECMWF runs (GRIB). Same engineering cost. |

## Web / scrape (fragile, ToS-sensitive — last resort)
Google weather (uses weather.com), weather.com, BBC Weather, AccuWeather,
timeanddate.com, MeteoBlue, Windy, Ventusky. No clean free API; scraping is brittle
and may breach terms. Only worth it for the settlement source (Wunderground).

## The honest caveat: diminishing returns
Most consumer weather apps display the **same underlying physical models** (GFS,
ECMWF). So ten APIs ≈ two or three *independent* signals. The real leverage is:
1. **Never go dark** (multi-source fallback — done).
2. **Match the settlement source** (Wunderground) — the biggest accuracy win.
3. A *few* genuinely independent models blended (Open-Meteo's ensemble already does
   this) — not a pile of correlated ones.

## Recommended build order
1. ✅ Open-Meteo + Met.no + NWS fallback (done — never goes dark).
2. Add **WeatherAPI.com** (1M/mo) + **Visual Crossing** as extra free members (signup, no card).
3. **Wunderground scrape** for the settlement station of the top markets — the real edge.
4. (Only if serious) raw NOAA/ECMWF GRIB for a self-hosted, uncapped ensemble.
