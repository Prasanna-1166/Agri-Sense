# API Reference

All responses are JSON. Error responses follow:
```json
{"success": false, "error": {"code": "INSUFFICIENT_DATA", "message": "..."}}
```
(Some legacy endpoints inherited from the earlier CropWise version return
a flatter `{"error": "..."}` shape - both are documented below per
endpoint. Stack traces are never returned to the client; see `app.py`
error handlers.)

## Health

**GET `/api/health`**
Returns model load status, dataset/accuracy metadata, and Crop Master summary.

## Location

**GET `/api/location/search?q=<text>`** — Nominatim place search
**GET `/api/location/reverse?lat=&lon=`** — Reverse geocode to a place name
**GET `/api/location/states`** — List Indian states
**GET `/api/location/districts?state=<name>`** — List districts (full lists for AP/Telangana)
**GET `/api/location/resolve?lat=&lon=`** — Resolve GPS to state/district + confirmation prompt text

## Environment / Weather / Soil

**POST `/api/environment`** `{lat, lon}` — Full climate+soil profile with source/status/confidence per value
**GET `/api/weather?lat=&lon=`** — Current conditions + 7-day forecast (Open-Meteo)
**POST `/api/soil`** `{lat, lon}` — Soil profile only
**POST `/api/soil/validate`** `{ph?, ec?, organic_carbon?, N?, P?, K?, sulphur?, zinc?, iron?, manganese?, copper?, boron?}` — Validates Soil Health Card values you supply; empty body returns an explicit "no soil test available" response
**POST `/api/soil/extract`** multipart file upload (`file` field, PDF/PNG/JPG, max 8MB) — Attempts extraction; response always requires frontend confirmation before use

## Prediction — Planning Mode

**POST `/api/predict/quick`** `{lat, lon, area_ha?, irrigation?}` — Location only
**POST `/api/predict/assisted`** (default) `{lat, lon, area_ha?, irrigation?, N?, P?, K?, temperature?, humidity?, ph?, rainfall?}` — Auto-fill + optional overrides
**POST `/api/predict/expert`** `{N, P, K, temperature, humidity, ph, rainfall, area_ha?, irrigation?, lat?, lon?}` — All 7 fields required
**POST `/api/predict`** — Generic, routes by `"mode"` field

All three return: `ranked_crops[]`, `top_crop`, `feature_importance[]`,
`data_quality`, `water_requirement`, `insights[]`, `risks[]`. `ranked_crops`
only ever contains the 22 model-supported crops - never an unsupported one.

## Current Farm Mode

**POST `/api/farm/analyze-current`**
```json
{
  "lat": 16.5, "lon": 80.6,
  "current_crop": "rice", "crop_stage": "flowering (optional)",
  "area_ha": 2, "irrigation": "partial",
  "N": 80 
}
```
If `current_crop` has no validated model coverage (e.g. `chilli`,
`tobacco`, `wheat`, `sugarcane`, `turmeric`, `groundnut`), the response has
`"suitability_available": false`, `"yield_available": false`, and a plain-
language `"message"` explaining why - weather/soil context is still
returned. If supported, `"crop_analysis"` contains suitability/yield/
explanation for that specific crop.

## Crops

**GET `/api/crops[?category=]`** — Full Crop Master registry (supported + unsupported)
**GET `/api/crops/<crop_id>`** — Single crop's registry entry
**POST `/api/crops/compare`** `{N, P, K, temperature, humidity, ph, rainfall, area_ha?, irrigation?, crops: [ids]}` — Compare specific crops; requesting an unsupported crop returns its reason instead of a fabricated comparison row

## Crop Plan & Economics

**GET `/api/crop-plan/<crop_id>?area_ha=<number>`** (`area_ha` optional, default 1.0)
Returns duration, planting-material requirement, fertilizer recommendation,
plant-protection guidance, and a cost breakdown for `crop_id`, scaled to
`area_ha`. Every field carries a `status` of `VERIFIED_SOURCE` or
`UNAVAILABLE` (never a silent fabrication) plus a `source` when verified.
Works for any crop in the Crop Master registry, including ML-unsupported
ones (`ml_recommendation_supported: false` + `ml_support_note` explains
why, independent of whether agronomic reference data exists). Returns
`404` for a crop id not in the Crop Master at all, and `400` for a
non-numeric or non-positive `area_ha`. See `docs/data-sources.md` §7 for
exactly which crops/fields have verified data today.

## Revenue & Gross Margin

**GET `/api/revenue/<crop_id>?production_t=<n>&area_ha=<n>&lat=<n>&lon=<n>`**
(or `&state=<name>&district=<name>` instead of lat/lon). `production_t`
and `area_ha` are optional (default 1.0 for area); without a production
figure, revenue is honestly `UNAVAILABLE`. Fetches a reference market
price (AGMARKNET via data.gov.in - see `data-sources.md`), reuses the
existing crop-plan cost figure, and returns:
`{ crop, production_t, market_price: {...}, gross_revenue_inr, cost_for_farm_inr, cost_source, gross_margin_inr, gross_margin_label, status, note, disclaimer }`.
`gross_margin_label` is always "Estimated Gross Margin", never "profit".
Returns `404` for an unknown crop, `400` for invalid `area_ha`/`production_t`.
A missing/failed market price or missing cost never causes an error
status - the relevant field is just `null` with an explanatory `note`.

## Crop Calendar

**GET `/api/crop-calendar/<crop_id>?sowing_date=YYYY-MM-DD`** (optional)
Returns `{ crop, sowing_date, duration, harvest_window, day_anchored_events, stage_notes, disclaimer }`.
`harvest_window` is only populated when both a sowing date and a
`VERIFIED_SOURCE` duration exist for the crop (pure date arithmetic on
already-sourced numbers). `day_anchored_events` and `stage_notes` reuse
existing Crop Plan agronomy data (fertilizer/plant-protection stage
text and a handful of explicitly sourced day-offsets) - no new crop
stages are invented. Returns `404` only for a crop unknown to the Crop
Master registry.

## Farm Dashboard / History enrichment

**PATCH `/api/history/<prediction_id>`** — body may include any of
`estimated_cost`, `market_price_modal_per_quintal`, `market_name`,
`estimated_revenue`, `estimated_gross_margin` (any other key is
ignored). Used by `crop_plan.js`/`revenue.js` to fill in figures that
load asynchronously after the base prediction was already saved.
Returns `404` if the id isn't found, `400` if no recognized field was
given.

**GET `/api/history/summary`** — Farm Performance Dashboard stats,
computed only over history records that actually have each field (see
`PredictionHistory.get_farm_summary()` in `utils/cache.py`). Returns
`{ total_predictions, unique_crops_evaluated, latest_recommended_crop, average_predicted_yield_t_per_ha, average_predicted_yield_sample_size, average_estimated_cost_inr, average_estimated_cost_sample_size, average_gross_margin_inr, average_gross_margin_sample_size, yield_trend, insufficient_data }`.
`insufficient_data: true` (with no other stats) when history is empty;
`yield_trend` (`"up"`/`"down"`/`"stable"`) only appears once at least 4
yield-bearing records exist.

## AgriSense Assistant (chatbot)

**POST `/api/chat`** — body: `{ "message": "...", "context": {...}, "history": [...] }`
`context` is a small object the frontend builds from data it already
has (current prediction + crop plan) - the backend does no independent
lookups, so there is one source of truth. `history` is the last few
`{role, content}` turns from this browser session (nothing is stored
server-side). Returns `{ "reply": "..." }` on success. Returns a clean
`{ "error": "...", "code": "..." }` — never a raw 500 — for: empty
message (`EMPTY_MESSAGE`, 400), message over 800 characters
(`MESSAGE_TOO_LONG`, 400), no `LLM_API_KEY` configured
(`NOT_CONFIGURED`, 503), or any LLM API failure/timeout/bad response
(`TIMEOUT` / `REQUEST_FAILED` / `API_ERROR` / `INVALID_RESPONSE`, all
503). See `docs/architecture.md` "AgriSense Assistant" and
`docs/limitations.md` for what this chatbot does and does not do.

## Farm Profile (optional, local, no auth)

**GET `/api/farm/profile`** / **POST `/api/farm/profile`** / **DELETE `/api/farm/profile`**

## History

**GET `/api/history?limit=`** / **POST `/api/history`** / **DELETE `/api/history/<id>`** / **DELETE `/api/history`**


## Public pages & crawler endpoints (not under /api)

| Path | Description |
|---|---|
| `GET /robots.txt` | Allows crawling, disallows `/api/`, links the sitemap. |
| `GET /sitemap.xml` | Generated live: `/`, `/crops`, `/privacy` and one URL per crop that has sourced data. Absolute URLs from `SITE_URL` (or the request host). |
| `GET /crops`, `GET /crops/<crop_id>` | Server-rendered crop guides. Crops without sourced data return a `noindex` page; unknown ids return 404. |
| `GET /privacy` | Privacy notice. |
| `GET /site.webmanifest`, `GET /favicon.ico` | App metadata / favicon redirect. |

## Cross-cutting behaviour

- **Visitor cookie:** the first visit to `/` (or first history/profile call) sets `agrisense_vid`
  (HttpOnly, SameSite=Lax, 1 year; `Secure` over HTTPS). It scopes `/api/history*` and
  `/api/farm/profile` to that browser. Static files, crawlers and pages never receive it.
- **Rate limits (429):** exceeding a limit returns `{"error": "...", "code": "RATE_LIMITED", "retry_after_seconds": n}`
  with a `Retry-After` header. Per IP per minute: chat 12, predictions 30, soil upload 10, geocoding 40,
  environment 30, revenue 30.
- **Errors:** 405/400/etc. under `/api/` keep their real status code with
  `{"success": false, "error": {"code", "message"}}`; API responses are sent with `Cache-Control: no-store`.
