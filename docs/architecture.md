# Architecture

## Overview

AgriSense AI is a modular Flask application with a single-page dashboard
frontend. It is intentionally NOT a microservices architecture — see
"Why not more infrastructure?" below.

```
AgriSense-AI/
├── app.py                 Flask app factory + entry point
├── config/                 Central configuration
│   ├── settings.py          Paths, feature lists, dataset config
│   ├── crop_master.py       THE crop data-availability registry (see data-sources.md)
│   ├── crop_agronomy_data.py THE crop agronomy/economics registry (seed, fertilizer,
│   │                          duration, plant protection - see data-sources.md §7)
│   └── geography.py         India state/AP+Telangana district reference data
├── ml/                      Training (offline) + inference (online)
│   ├── train_crop_model.py  Trains RandomForestClassifier, writes models/
│   ├── train_yield_model.py Trains RandomForestRegressor (synthetic target)
│   ├── predictor.py         Loads trained models, runs inference ONLY
│   ├── preprocessing.py     Dataset loading/cleaning/synthetic-yield generation
│   └── explainability.py    Feature importance + "why this crop" checklist
├── services/                External integrations, one per concern
│   ├── geocoding_service.py   Nominatim search/reverse
│   ├── weather_service.py     Open-Meteo current/forecast/climate-average
│   ├── soil_service.py        SoilGrids + regional fallback + Soil Health Card validation
│   ├── soil_extraction_service.py  PDF/image soil-report text extraction
│   ├── environment_service.py Orchestrates weather+soil into one profile
│   ├── risk_service.py        Rule-based rainfall/temperature/irrigation risk
│   └── agronomy_service.py    Crop Plan Layer: scales agronomy data to farm
│                               area and assembles the (honestly-unpriced) cost
│                               breakdown - see "Crop Plan Layer" below
├── routes/                  Flask blueprints (one per resource)
│   ├── health.py, location.py, environment.py, prediction.py, history.py
│   ├── crops.py             Crop Master + comparison
│   ├── soil.py               Manual soil validation + report upload
│   ├── farm.py                Optional farm profile (stored per visitor)
│   ├── seo.py                 robots.txt, sitemap.xml, /crops guides, /privacy, manifest
│   ├── current_farm.py       Current Farm Mode (situational analysis)
│   ├── crop_plan.py          GET /api/crop-plan/<crop_id>?area_ha=.. (Crop Plan Layer)
│   ├── chat.py                POST /api/chat (AgriSense Assistant - see below)
│   ├── revenue.py             GET /api/revenue/<crop_id> (Revenue & Gross Margin)
│   └── calendar.py            GET /api/crop-calendar/<crop_id> (Crop Calendar)
├── utils/                   validation, caching, history storage, helpers, logging, units.py
├── templates/, static/      Frontend (no HTML/JS embedded in Python)
│                            static/js/crop_plan.js renders the Crop Plan & Economics page
│                            static/js/chat.js renders the AgriSense Assistant chat widget
│                            static/js/revenue.js, calendar.js render their Crop Plan sub-cards
│                            static/js/dashboard.js also renders the Farm Summary card
│                            static/js/history.js also renders the 4 history charts (Chart.js)
├── models/                   Trained model artifacts + metadata.json
├── data/                     Cached dataset, local prediction history, uploads/ (transient)
├── tests/                    pytest suite (248 tests)
└── docs/                     This documentation set

## Revenue, Crop Calendar & Farm Dashboard (Decision Support Layer)

These three features share one data flow and duplicate nothing:

```
Existing ML prediction (unchanged)
        |
        v
Crop Plan Layer (config/crop_agronomy_data.py, services/agronomy_service.py)
        |
        +--> services/revenue_service.py
        |        - reuses agronomy_service.get_crop_plan()'s cost (surveyed_total
        |          or itemized) - no separate cost calculation
        |        - reuses services/market_price_service.py for price
        |        - revenue = production x price; gross margin = revenue - cost
        |          (never called "profit" - see revenue_service.py docstring)
        |
        +--> services/calendar_service.py
        |        - reuses config/crop_agronomy_data.py's `duration` and the new
        |          `calendar_events` field (day-offsets already present in
        |          existing fertilizer/plant-protection text, e.g. cotton's
        |          "25-30 and 60-65 days after sowing") - invents no new stages
        |
        +--> utils/cache.py PredictionHistory.get_farm_summary()
                 - aggregates ONLY over existing history records' fields;
                   an "insufficient_data" flag replaces any average that
                   can't honestly be computed yet
```

`services/market_price_service.py` calls the official Government of India
Open Government Data (OGD) Platform resource "Current Daily Price of
Various Commodities from Various Markets (Mandi)" (AGMARKNET data,
resource id `9ef84268-d588-465a-a308-a864a43d0070`), tries district ->
state -> national scope, and caches results (6h TTL, via the same
`SimpleCache` weather_service.py already uses) so revenue, the
dashboard, history, and the chatbot all share one fetched price rather
than calling the external API repeatedly. This is an OPTIONAL data
source: any failure (network, timeout, no record, unmapped commodity)
degrades to an honest `UNAVAILABLE` result - it never affects crop
recommendation, yield prediction, or the rest of the crop plan, which
have no dependency on it at all.

History entries get cost/market-price/revenue/margin fields filled in
asynchronously via `PATCH /api/history/<id>` once crop_plan.js/revenue.js
finish loading (they load after the base prediction is already saved),
rather than restructuring the prediction-save flow - this keeps
backward compatibility with pre-existing history records trivial (see
`docs/limitations.md`): a record simply never gets patched and its new
fields stay `None`, which every consumer (list rendering, charts, farm
summary) already handles.

## AgriSense Assistant (simple chatbot)

Deliberately minimal, per project requirements - no RAG, no vector
database, no multi-agent orchestration, no server-side conversation
storage:

```
Browser (static/js/chat.js)
  - holds conversation history in a plain JS array (session-only,
    lost on page reload - nothing is persisted server-side)
  - on each message, builds a small context object from data ALREADY
    fetched by prediction.js/crop_plan.js (CropWise.state.lastPrediction,
    CropWiseCropPlan.lastPlan) - it does no new lookups of its own
        |
        v
POST /api/chat  { message, context, history }
        |
        v
routes/chat.py  - validates input (non-empty, length-capped), never lets
                  an exception escape as a raw 500
        |
        v
services/chat_service.py
  - build_context_block(context): formats the frontend-supplied data
    into plain text, one line per AgriSense fact, with UNAVAILABLE
    written out explicitly wherever the source data says so. Now also
    formats revenue/gross-margin, crop-calendar, and farm-history-summary
    data when the frontend supplies them (chat.js reads
    CropWiseRevenue.lastRevenue, CropWiseCalendar.lastCalendar, and
    CropWiseDashboard.lastFarmSummary) - same reuse-only, no-new-data-copy
    principle as the crop plan context.
  - ask_assistant(): sends a system message (instructions + context)
    plus recent history to an OpenAI-compatible chat completions API
    (config.settings.LLM_API_URL/LLM_MODEL/LLM_API_KEY - defaults to
    Groq, which has a free, no-credit-card tier; any other
    OpenAI-compatible provider works by changing the URL/model)
  - the LLM only explains numbers AgriSense already computed - it is
    given a hard system-prompt instruction never to invent yield,
    seed rate, fertilizer dose, cost, or duration figures of its own
```

This is intentionally a *read-only consumer* of the same Crop Plan
Layer and prediction pipeline described above - it has no separate copy
of any agricultural data, per the single-source-of-truth requirement.
If the `LLM_API_KEY` environment variable is unset, every other
AgriSense feature works normally; only `/api/chat` returns a clear
"not configured" message instead of a reply (see `docs/limitations.md`).

## Crop Plan Layer (agronomy + economics)

Added to complement the ML prediction pipeline without touching it:

```
ML pipeline (unchanged):
  Location → Environmental data → ML crop recommendation → ML yield estimate → ranked crops

Crop Plan Layer (new, independent):
  crop_id + farm area_ha
    → config/crop_agronomy_data.py   (single source of truth, sourced values only)
    → services/agronomy_service.py   (scales quantity_per_ha × area_ha; builds cost
                                       breakdown as quantity × unit_price = cost,
                                       currently unpriced everywhere - see data-sources.md §7)
    → GET /api/crop-plan/<crop_id>   (routes/crop_plan.py)
    → static/js/crop_plan.js          (renders Crop Plan & Economics page)
```

This is a **read-only consumer** of `ml/predictor.py`'s output (it takes a
`crop_id` string, typically `top_crop.crop` from a prediction response) and
never recomputes, overrides, or feeds back into the crop/yield models. It is
exposed as its own endpoint rather than folded into `/api/predict/*` so the
two concerns - ML suitability/yield vs. agronomic planning/cost - stay
independently testable and independently extensible (see
`docs/limitations.md` for what is not yet covered, and the "Future
extensibility" note below).

**Future extensibility:** the schema in `crop_agronomy_data.py` and the
cost-calculation shape in `agronomy_service.py` were designed so that adding
market-price data, irrigation scheduling, a crop calendar, or multilingual
labels later requires adding fields/files, not restructuring what already
exists.
```

## Data flow (Planning Mode)

```
Location (map/search/GPS/state-district)
        │
        ▼
environment_service.build_environment_profile(lat, lon)
        │           (calls weather_service + soil_service)
        ▼
merge_with_user_overrides()  ← optional manual/soil-test values
        │
        ▼
ml.predictor.predict_recommendations()
        │           (loads pre-trained models, never trains here)
        ▼
risk_service.build_risk_summary()
        │
        ▼
JSON response → frontend renders Dashboard/Recommendation/Yield/Insights/Risk
```

## Data flow (Current Farm Mode)

Same environment/soil pipeline, but instead of ranking all 22 crops, it
looks up `config.crop_master.is_crop_supported(current_crop)` first:

- If unsupported (e.g. Chilli, Tobacco) → returns weather/soil context only,
  with an explicit "no validated model coverage" message. No fabricated
  suitability or yield is generated.
- If supported → `ml.predictor.predict_for_specific_crop()` evaluates that
  one crop's suitability/yield against current conditions.

## Why not more infrastructure?

Per the project's own engineering constraints: no unnecessary
microservices, message queues, or heavy databases. Local prediction
history and the optional farm profile use plain JSON files — SQLite would
be a reasonable next step only if history/profile scale requirements grow
beyond a single farmer's local usage.

## Models are trained offline, loaded online

`app.py` never calls the training scripts on a web request. Training is a
deliberate, separate step (`python -m ml.train_crop_model`), producing
versioned artifacts in `models/` plus `models/metadata.json` recording
dataset size, accuracy, and training timestamp. The running app only
calls `ml/predictor.py::load_models()`, which fails soft (returns a
"models not trained" 503) rather than crashing if artifacts are missing.


## Production layer (deployment, SEO, per-visitor data)

Added to make the app safe to run on a public website; it does not touch the ML pipeline.

- **Per-visitor data** (`utils/visitor.py`): there are no accounts, so each browser gets a random
  `agrisense_vid` cookie that selects its own folder `<data dir>/users/<id>/` holding that visitor's
  `prediction_history.json` and `farm_profile.json`. Visitors cannot see or delete each other's data;
  idle folders are pruned after 90 days. Ids are validated as 32 hex chars (no path traversal).
- **Safe storage** (`utils/cache.py`): history uses a per-file lock and atomic writes, and creates
  nothing on disk until the first save.
- **Rate limiting** (`utils/ratelimit.py`): in-memory per-IP sliding window on chat, prediction,
  upload, geocoding, environment and revenue endpoints (429 + `Retry-After`).
- **App hooks** (`app.py`): optional `ProxyFix` (`AGRISENSE_BEHIND_PROXY=1`), security headers, HSTS in
  production, `/static` URLs versioned per deploy, real 404 pages, and genuine HTTP status codes for
  405/400/etc. instead of a blanket 500.
- **SEO** (`routes/seo.py`, `templates/`): server-rendered crop guides built from
  `services/agronomy_service.get_crop_plan()` (the same single source of truth as the app and chatbot);
  only crops with sourced data are indexable. Shared head tags live in `templates/_head_meta.html`.
- **Serving** (`gunicorn.conf.py`, `render.yaml`, `Dockerfile`): one gunicorn worker with 4 threads
  (~240 MB RAM), configured entirely by environment variables (see `docs/deployment.md`).
