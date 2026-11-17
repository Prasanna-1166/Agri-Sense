# 🌾 AgriSense AI

[![CI](https://github.com/Prasanna-1166/AgriSense-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/Prasanna-1166/AgriSense-AI/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Prasanna-1166/AgriSense-AI)

**An honest, real-data agricultural decision-support platform for Andhra Pradesh & Telangana.**

AgriSense AI combines a validated crop-suitability ML model, live weather,
location-based soil intelligence, and optional real soil-test data to help
answer: *"Given my farm location, season, soil, irrigation, and current
weather, what crop is most suitable, what yield can I reasonably expect,
and why?"* — and, just as importantly, **what this system honestly does
not know yet.**

> **Read `docs/limitations.md` before demoing this.** Six economically
> important crops for this region — Chilli, Tobacco, Wheat, Sugarcane,
> Turmeric, Groundnut — have **no validated model** in this version. The
> app says so explicitly everywhere they'd appear, rather than guessing.

**Quick start**

```bash
git clone https://github.com/Prasanna-1166/AgriSense-AI.git
cd AgriSense-AI
python -m venv venv && source venv/bin/activate      # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py                                         # → http://127.0.0.1:5000
```

**Deploy it** (free, ~5 minutes, no credit card): click the *Deploy to Render* button
above, or follow [`docs/deployment.md`](docs/deployment.md). **Live demo:** add your URL
here after your first deploy.

**Contents:** [Features](#2-features) · [Install](#9-installation) · [Config](#10-environment-variables) ·
[Tests](#14-testing) · [Deploy](#17-deployment) · [Security & privacy](#21-security--privacy) ·
[Contributing](#22-contributing--license)

---

## 1. Project Overview

This is a from-scratch rebuild of an earlier single-file "Smart Crop"
demo (~2,200-row dataset, 22 crops) into a modular, two-mode agricultural
platform:

- **Planning Mode** — "What crop should I plant?" (Quick / Smart Assisted / Expert input tiers)
- **Current Farm Mode** — "I have a crop already — help me understand my situation"

with a Crop Master registry that treats data availability as a first-class
concept, a rule-based risk layer, Soil Health Card-style soil intelligence
with document upload, an optional local farm profile, and full data-source
transparency throughout.

## 2. Features

- **Location-first**: map click, search, GPS (with a confirm-your-district step), or manual State→District (full lists for AP & Telangana)
- **Three Planning input tiers** + **Current Farm situational analysis**
- **Crop Master registry**: 22 crops with real validated data, 6 explicitly marked "data unavailable" — see `/api/crops` and the Crop Directory page
- **Soil intelligence**: manual Soil Health Card entry (pH, EC, OC, N/P/K, S/Zn/Fe/Mn/Cu/B), PDF/image report upload with mandatory confirm-before-use, SoilGrids/ISRIC-based pH estimate, transparent fallback chain
- **Explainable recommendations**: feature importance + "why this crop" checklist derived directly from real training-data statistics
- **Yield estimation with range**, always labeled as a documented synthetic/estimated model
- **Rule-based risk assessment** (rainfall/temperature/irrigation/data-availability), each with its exact triggering rule shown
- **Crop comparison, weather & 7-day forecast, prediction history, optional local farm profile**
- **Crop Plan & Economics**: seed/planting-material requirement, crop duration, fertilizer
  recommendation, and plant-protection guidance for the recommended crop, scaled to your farm
  area, each field tagged verified-source/derived-estimate/honestly-unavailable — see
  `/api/crop-plan/<crop_id>` and `docs/data-sources.md` §7. For rice, maize and cotton, a real
  published cost-of-cultivation survey total (₹/ha, with region/year/source) is also shown; other
  crops show sourced input quantities with cost left unavailable rather than guessed.
- **AgriSense Assistant**: a simple chatbot (floating widget) that answers questions about your
  current recommendation, yield, seed, fertilizer, cost, revenue, calendar, and farm history using
  AgriSense's own sourced data — no RAG, no vector database, no separate data copy. Optional
  (`LLM_API_KEY`); see `docs/architecture.md` "AgriSense Assistant" and `docs/limitations.md`.
- **Revenue & Return Estimate**: reference market price (AGMARKNET via data.gov.in, modal price with
  market/date/source shown) × predicted production = expected gross revenue; minus the existing
  cultivation-cost figure = **Estimated Gross Margin** (never called "profit") — honestly
  unavailable when no verified price or cost exists. See `/api/revenue/<crop_id>`.
- **Crop Calendar**: sowing date + verified crop duration → an estimated harvest window, plus any
  day-since-sowing agronomy events already sourced in the Crop Plan data (cotton, blackgram,
  papaya) — no invented stages. See `/api/crop-calendar/<crop_id>`.
- **Farm Dashboard**: a Farm Summary card (predictions made, crops evaluated, average yield/cost/
  margin, yield trend — each computed only from records that actually have that field) plus 4
  history charts (yield, cost, crop counts, revenue/margin over time). See `/api/history/summary`.
- **Crop guides** (`/crops`): a server-rendered, search-engine-friendly page for each of the 17 crops that has sourced agronomy data, with a `sitemap.xml`, canonical URLs and structured data. Crops without sourced data get no page.
- **Never fabricates**: unsupported crops get an honest message, not a guess; every environmental value carries a source/status/confidence tag

## 3. Architecture

See `docs/architecture.md` for the full breakdown. Short version: modular
Flask blueprints (`routes/`), isolated external-service wrappers
(`services/`), training/inference split (`ml/`), a Crop Master + geography
reference registry (`config/`), and a vanilla-JS multi-section dashboard
frontend (`templates/`, `static/`).

## 4. Technology Stack

- **Backend**: Flask 3, Python 3.12
- **ML**: scikit-learn (RandomForestClassifier + RandomForestRegressor), pandas, NumPy, joblib
- **Frontend**: Server-rendered Jinja2 + vanilla JS + Leaflet (map) + Chart.js (charts) — no build step required
- **Soil report extraction**: pypdf (PDF text) + optional pytesseract/Pillow (image OCR)
- **Storage**: plain JSON files for prediction history / farm profile, kept in a private folder per anonymous visitor (no database, no accounts — see `docs/architecture.md`)
- **Production**: gunicorn, deployed on Render (`render.yaml`) or any Docker host (`Dockerfile`)

## 5. Datasets

See `docs/data-sources.md` for the complete, honest breakdown, including
what real Andhra Pradesh/Telangana government sources were researched but
**not yet integrated**, and exactly why.

## 6. Data Sources (summary)

| Purpose | Source | Real / Synthetic |
|---|---|---|
| Crop recommendation training | Public Crop Recommendation Dataset (22 crops) | Real |
| Yield estimation training | Reference average yields, scaled by real per-crop statistics | **Synthetic** — always labeled as such |
| Weather / forecast / elevation | Open-Meteo | Real, live |
| Soil pH estimate | SoilGrids / ISRIC | Real, modeled (not lab-measured) |
| Soil N/P/K (automatic) | Regional/climatic-zone estimate | Estimate, not measured |
| Soil N/P/K/pH (manual) | Your Soil Health Card / lab test | Real, if you enter it |
| Location search/reverse | OpenStreetMap Nominatim | Real |
| State/district names | Static administrative reference | Real |

## 7. ML Methodology

See `docs/ml-methodology.md`. Crop model: RandomForestClassifier,
99.22% test accuracy on the crops it was trained on. Yield model:
RandomForestRegressor on a documented synthetic target — see
`docs/data-sources.md` §2 before quoting this number anywhere.

## 8. Model Evaluation

Regenerated on every training run into `models/metadata.json`:
- Crop model: accuracy, dataset size/source, training timestamp
- Yield model: R², MAE, explicit "synthetic/estimated" note

## 9. Installation

Requires **Python 3.12** (the pinned numpy/pandas/scikit-learn have no wheels for newer versions).

**macOS / Linux**
```bash
cd AgriSense-AI
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
cd AgriSense-AI
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
If PowerShell blocks script execution, run once: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

To run the tests too, install `requirements-dev.txt` instead.

## 10. Environment Variables

Everything is optional. For local use, copy the template and edit the copy:

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

`.env` is loaded automatically (via `python-dotenv`) and is **git-ignored — never put a
real key in `.env.example`, which is committed.** On a hosting platform, set the same
names in its dashboard instead. The full list, with explanations, is in [`.env.example`](.env.example).

| Variable | Purpose |
|---|---|
| `LLM_API_KEY` | Enables the AgriSense Assistant chat (free key from console.groq.com). Unset = chat disabled, everything else works. |
| `DATA_GOV_IN_API_KEY` | Your own data.gov.in key for market prices (default: shared public sample key, rate-limited). |
| `SITE_URL` | Your public address — used for canonical URLs, `sitemap.xml`, social cards. Set it in production. |
| `AGRISENSE_ENV`, `AGRISENSE_BEHIND_PROXY` | `production` / `1` on a real host (HSTS, long static caching, real client IPs). |
| `AGRISENSE_DATA_DIR` | Where runtime data lives (point at a persistent disk if you have one). |

## 11. Development — Running the App

Models are pre-trained and bundled in `models/`, so this works immediately:

```powershell
python app.py
```
Open **http://127.0.0.1:5000**.

## 12. Training / Retraining Models

Never run automatically by the web app — always an explicit step:

```powershell
python -m ml.train_crop_model
python -m ml.train_yield_model
```

## 13. Refreshing Data

The crop dataset is re-downloaded automatically the next time you run
`train_crop_model` with an empty/deleted `data/crop_dataset_cache.csv`.
There is no live-updating agricultural dataset in this version — see
`docs/limitations.md`.

## 14. Testing

```powershell
python -m pytest tests/ -v
```
The suite runs against a throw-away data folder with blank API keys, so it never touches your real data or spends your LLM quota. It runs automatically on every push via GitHub Actions (`.github/workflows/ci.yml`).

**248 tests**, including dedicated anti-fabrication checks (e.g.
`test_supported_crops_match_trained_model_classes` fails loudly if the
Crop Master registry and the actual trained model ever disagree about
which crops are supported, `test_no_crop_has_a_fabricated_cost_total`
for the Crop Plan & Economics layer, a full mocked-LLM suite in
`tests/test_chat.py`, and `tests/test_revenue.py` /
`tests/test_calendar.py` / `tests/test_dashboard.py` verifying revenue,
crop-calendar, and farm-dashboard figures are only ever shown when a
real source backs them). `tests/test_seo.py` checks that `sitemap.xml`, canonical tags, structured data and `noindex` rules are correct, and `tests/test_deployment.py` covers per-visitor data isolation, rate limiting, security headers, proxy handling and thread-safety.

## 15. API Reference

See `docs/api.md` for every endpoint.

## 16. Project Structure

See `docs/architecture.md`.

## 17. Deployment

**Recommended host: [Render](https://render.com)** (free web service — no credit card, free HTTPS and
custom domain, auto-deploys from GitHub). The app needs ~240 MB RAM, so it fits the free 512 MB tier.

1. Push this repository to GitHub.
2. Render → **New → Blueprint** → select the repo (`render.yaml` configures everything).
3. When asked, set `SITE_URL` (and optionally `LLM_API_KEY` / `DATA_GOV_IN_API_KEY`).

Free services sleep after 15 minutes idle (first visit then takes ~30–60 s). Step-by-step instructions,
custom domains, keeping the site awake, the Docker alternative, and the post-deploy SEO checklist
(Google Search Console, sitemap submission) are in [`docs/deployment.md`](docs/deployment.md).

## 18. Troubleshooting

- **"Models not yet trained" / 503 on predict endpoints** → run the training commands in §12.
- **A crop shows "data unavailable"** → this is intentional, not a bug — see `docs/limitations.md`. Chilli, Tobacco, Wheat, Sugarcane, Turmeric, and Groundnut have no validated model in this version.
- **Weather/soil/location shows `fallback` status** → your network can't reach `nominatim.openstreetmap.org` / `api.open-meteo.com` / `rest.isric.org`. The app still works; those values just won't be `retrieved`/`estimated`.
- **Soil report upload says extraction failed** → this is expected for unusual formats or if `pypdf`/`pytesseract` aren't installed; use manual entry instead.
- **`pip install` fails** → confirm Python 3.12, and that the venv is activated.

## 19. Limitations

**Read `docs/limitations.md` in full before evaluating or demoing this
project.** The short version: 6 of 9 mandatory crops are explicitly
unsupported due to a real training-data gap, yield figures are a
documented synthetic estimate, and real Andhra Pradesh/Telangana
government production data was researched but not yet integrated.

## 20. Future Work

See `docs/limitations.md` §Future Work — headlined by integrating real
district-level government production data, which is the single highest-
value next step for this project.

---

## 21. Security & Privacy

- **No secrets in the repo.** API keys come from environment variables; `.env` is git-ignored. See [`SECURITY.md`](SECURITY.md).
- **No accounts, no analytics, no ads.** History and the optional farm profile are stored per anonymous visitor (a random first-party cookie), so visitors cannot see each other's data; idle data is auto-deleted after 90 days. Details are on the in-app privacy page (`/privacy`; source: [`templates/privacy.html`](templates/privacy.html)).
- **Abuse protection:** per-IP rate limits on the chat, prediction, upload and geocoding endpoints; security headers; request-size limit.

## 22. Contributing & License

Contributions are welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md). The one rule that matters
here: **never add an agricultural value without a named, dated source.**
Released under the [MIT License](LICENSE).

---

*This README was written to be read alongside `docs/limitations.md` —
together they are the actual, current state of the project, not an
aspirational description of it.*
