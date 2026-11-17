# Deployment guide

This guide takes AgriSense AI from your laptop to a public HTTPS website, for free, and sets it up so
search engines can find it.

**Contents:** [TL;DR](#tldr) · [Why Render](#why-render) · [Before you push to GitHub](#before-you-push-to-github) ·
[Deploy on Render](#deploy-on-render-step-by-step) · [Configuration](#configuration-reference) ·
[Custom domain](#custom-domain) · [Keep it awake](#keeping-the-free-site-awake) ·
[Data & persistence](#data-and-persistence) · [SEO checklist](#seo-launch-checklist) ·
[Docker / other hosts](#docker-and-other-hosts) · [Operations](#operations) · [Troubleshooting](#troubleshooting)

---

## TL;DR

1. Clean your local git history of the leaked key and push to GitHub → [section below](#before-you-push-to-github).
2. Render → **New → Blueprint** → pick the repo. `render.yaml` configures everything.
3. Fill in `SITE_URL` (and optionally `LLM_API_KEY`, `DATA_GOV_IN_API_KEY`) when prompted.
4. Open `https://<your-service>.onrender.com/api/health`, `/robots.txt` and `/sitemap.xml` to confirm.
5. Add the site to Google Search Console and submit `sitemap.xml` → [SEO checklist](#seo-launch-checklist).

---

## Why Render

AgriSense is a Flask app with scikit-learn models, a few small JSON files for state, and outbound calls to
OpenStreetMap, Open-Meteo, SoilGrids, data.gov.in and an LLM API. Measured on this codebase under
gunicorn: **~240 MB RAM, ~1.5 s startup.** That shaped the choice:

| Host | Verdict for this app |
|---|---|
| **Render (free web service)** ✅ | **Chosen.** Real Python/gunicorn hosting, no credit card, free HTTPS + custom domain, auto-deploy from GitHub, one-file config (`render.yaml`), 512 MB RAM fits the app twice over. Trade-offs: sleeps after 15 min idle; disk is wiped on redeploy. |
| Hugging Face Spaces (Docker) | Good free alternative with more RAM and no card. The app lives on a `*.hf.space` address and Spaces are aimed at ML demos, so it is a weaker home for a site you want to rank in search. Works with the included `Dockerfile`. |
| Google Cloud Run / Fly.io | Excellent and scale-to-zero, but need a credit card on file. Use the `Dockerfile` if you go this way. |
| PythonAnywhere (free) | Free accounts restrict outbound internet to an allow-list of sites, which would break weather/soil/geocoding/market-price lookups (check their current policy). |
| Vercel / Netlify | Built for static sites and short serverless functions; a Flask app with ML models and a writable data folder is a poor fit. |

> Free-tier terms change. Check Render's current free-tier page before relying on specific numbers.

**The one real trade-off is the 15-minute sleep.** A visitor (or Googlebot) arriving after idle waits
~30–60 s for the first response. See [Keeping the free site awake](#keeping-the-free-site-awake). The
paid *Starter* instance removes sleeping and adds persistent-disk support if you outgrow the free tier.

---

## Before you push to GitHub

### 1. A key was committed — revoke it first

Your local history contains an API key inside `.env.example` (commit `63a1e31`, "Chat bot setup").
**Those two commits have not been pushed**, so it has not reached GitHub — keep it that way:

1. **Revoke that key** at <https://console.groq.com> → *API Keys* (do this first, whatever else you do).
   Also consider rotating the key in your local `.env`: it was inside the project zip you shared.
2. Remove the two unpushed commits while keeping all your files, and stop tracking personal data:

```bash
git reset --soft origin/main            # drops the 2 local commits, keeps every file
git rm --cached data/farm_profile.json  # your personal farm profile must not be in the repo
git add -A
git status                              # CHECK: .env must NOT appear in this list
git commit -m "Production-ready: deployment, SEO, per-visitor data, security hardening"
git reflog expire --expire=now --all && git gc --prune=now --aggressive   # purge old objects locally
git log -p --all | grep -E "gsk_|sk-ant-|AIza" || echo "history is clean"
git push origin main
```

`.env` is already git-ignored, and `.env.example` now contains placeholders only.

### 2. Pre-push checklist

- [ ] `python -m pytest tests -q` passes.
- [ ] `git status` shows no `.env`, no `venv/`, no `data/users/`, no `data/farm_profile.json`.
- [ ] The history-check command above prints "history is clean".
- [ ] The repo has the files GitHub visitors expect: `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`,
      `.github/workflows/ci.yml` (the CI badge in the README turns green after the first push).
- [ ] In GitHub → *Settings → Code security*, enable **Secret scanning** and **Private vulnerability reporting**.

---

## Deploy on Render, step by step

1. Create a free account at <https://render.com> (sign in with GitHub — no card needed for free web services).
2. **New → Blueprint** → connect your GitHub account → select `AgriSense-AI`.
   (Or click the *Deploy to Render* button in the README.)
3. Render reads `render.yaml` and shows one web service, `agrisense-ai`, plan **Free**, region **Singapore**
   (closest to India). It asks for the values marked `sync: false`:

   | Prompt | What to enter |
   |---|---|
   | `SITE_URL` | `https://agrisense-ai.onrender.com` — or your custom domain if you already have one. If the name is taken Render adds a suffix; correct this later under *Environment*. |
   | `LLM_API_KEY` | Your **new** Groq key (optional — leave blank to disable the chat widget). |
   | `DATA_GOV_IN_API_KEY` | Your own data.gov.in key (optional — blank uses the shared public key). |
   | `GOOGLE_SITE_VERIFICATION` | Leave blank for now; fill it in during the [SEO step](#seo-launch-checklist). |

4. **Apply.** The first build takes ~3–5 minutes (installing numpy/pandas/scikit-learn).
5. When the service shows **Live**, verify:
   - `/api/health` → HTTP 200 with `"crop_model_loaded": true`
   - `/` → the app loads; run a prediction in Expert mode
   - `/sitemap.xml` and `/robots.txt` → show **your** URL, not `localhost`
   - `/crops/rice` → the rice guide
6. Every `git push` to `main` now redeploys automatically (`autoDeploy: true`).

Python is pinned to **3.12.7** in `render.yaml`. This matters: new Render services default to a newer
Python, for which the pinned numpy/pandas/scikit-learn have no wheels — the build would fail.

---

## Configuration reference

Set these under *Render → your service → Environment*. `render.yaml` already sets the first three.

| Variable | Value | Purpose |
|---|---|---|
| `PYTHON_VERSION` | `3.12.7` | Pins the Python runtime. |
| `AGRISENSE_ENV` | `production` | Long static caching, HSTS. |
| `AGRISENSE_BEHIND_PROXY` | `1` | Trust Render's proxy for real client IPs and `https` (needed for correct rate limiting, cookies and sitemap URLs). |
| `SITE_URL` | `https://your-domain` | Canonical URLs, sitemap, social cards. No trailing slash. |
| `LLM_API_KEY` | secret | Enables the chat assistant. |
| `DATA_GOV_IN_API_KEY` | secret | Market prices (own key recommended). |
| `GOOGLE_SITE_VERIFICATION` / `BING_SITE_VERIFICATION` | token | Search-engine ownership tags. |
| `AGRISENSE_DATA_DIR` | path | Point at a persistent disk (paid plans). Default `./data`. |
| `AGRISENSE_USER_DATA_RETENTION_DAYS` | `90` | Idle per-visitor data older than this is deleted at startup. |
| `AGRISENSE_RATE_LIMIT` | `1` | Set `0` only to disable the per-IP limiter (not recommended). |
| `WEB_CONCURRENCY` / `GUNICORN_THREADS` | `1` / `4` | Workers/threads. Keep 1 worker on a 512 MB instance. |

Blank values are treated as "unset", so an empty field in the dashboard never overrides a default.

---

## Custom domain

1. Render → service → **Settings → Custom Domains → Add**; enter e.g. `agrisense.yourdomain.in`.
2. Add the DNS record Render shows you at your registrar (usually a `CNAME`). HTTPS certificates are automatic.
3. **Change `SITE_URL` to the custom domain** and redeploy. Canonical tags and the sitemap then point at
   the domain, so the `*.onrender.com` address does not compete with it as duplicate content.
4. Re-submit the sitemap in Search Console under the new property.

---

## Keeping the free site awake

Free instances stop after 15 minutes without traffic and take ~30–60 s to wake. For a portfolio demo or
anything search engines should crawl reliably, avoid that:

- **Free:** create a monitor at <https://uptimerobot.com> (free plan, 5-minute interval) for
  `https://<your-site>/api/health`. A single always-on free service uses ~744 of the ~750 free
  instance-hours per month — **do not run a second free service in the same workspace** or you will run out.
- **Paid:** Render's *Starter* instance never sleeps and supports a persistent disk.

---

## Data and persistence

- AgriSense has **no database and no accounts.** The only server-side state is each visitor's prediction
  history and optional farm profile (small JSON files), stored in a private folder per anonymous browser
  (`<data dir>/users/<random-id>/`). Visitors cannot see each other's data.
- **On Render's free tier the disk is ephemeral:** history and profiles are wiped on every redeploy and
  restart. That is acceptable for a demo; to keep them, use a paid plan with a persistent disk and set
  `AGRISENSE_DATA_DIR` to its mount path.
- Idle visitor folders are deleted after 90 days (configurable). The in-app `/privacy` page describes all
  of this to users — update it if you change behaviour.
- Soil-report uploads exist on disk only for the instant they are processed.
- Photo OCR needs the Tesseract program, which Render's native Python runtime does not include; PDF
  extraction and manual entry still work, and the UI says when OCR is unavailable. The `Dockerfile`
  installs Tesseract if you need it.

---

## SEO launch checklist

The site ships with: `robots.txt`, a live `sitemap.xml`, canonical URLs, titles/descriptions, Open Graph &
Twitter cards, JSON-LD structured data, 17 server-rendered crop guides (`/crops/<crop>`), a privacy page,
real 404 responses, a web manifest and icons. What remains is telling the search engines.

1. **Set `SITE_URL`** to your final address (see above). Check `/sitemap.xml` shows it.
2. **Google Search Console** (<https://search.google.com/search-console>):
   - *Add property → URL prefix* → your site address.
   - Choose the **HTML tag** verification method. Copy only the `content="…"` value into the
     `GOOGLE_SITE_VERIFICATION` environment variable, redeploy, then click **Verify**.
     (With a custom domain you can use DNS verification instead.)
   - **Sitemaps → Add** `sitemap.xml` → Submit.
   - **URL Inspection →** paste your home page → **Request indexing**; repeat for `/crops`.
3. **Bing Webmaster Tools** (<https://www.bing.com/webmasters>): *Import from Google Search Console* (easiest),
   or add the site and set `BING_SITE_VERIFICATION`.
4. **Check link previews:** paste your URL into WhatsApp/LinkedIn/X — you should see the AgriSense card.
5. **Check quality:** run Lighthouse (Chrome DevTools → Lighthouse) on `/` and `/crops/rice`.
6. **Watch Search Console → Pages** over the following days for crawl or "noindex" issues.

**Honest expectations.** Indexing a new site typically takes days to a few weeks, and ranking depends on
competition and on other sites linking to yours. This setup removes technical obstacles; it cannot
guarantee a position. What helps most: link to the site from your GitHub README (done), LinkedIn,
college/portfolio pages and agriculture communities; keep the crop guides accurate; and add more crops
only when you have a real source for them (the sitemap picks new guides up automatically).

Design choices worth knowing:
- Crops without sourced data have **no indexable page** — they are left out of the sitemap and marked
  `noindex` if reached directly, so search engines never see thin placeholder content.
- Unknown URLs return a genuine **404**, not the app with HTTP 200 (which Google treats as a "soft 404").
- The dashboard itself is a JavaScript app at `/`; the crop guides and privacy page are plain server-rendered
  HTML, so they are fully readable by crawlers.

---

## Docker and other hosts

The `Dockerfile` runs the same gunicorn setup and works on any container host.

```bash
docker build -t agrisense-ai .
docker run --rm -p 8000:8000 --env-file .env agrisense-ai
# → http://localhost:8000
```

- **Hugging Face Spaces:** create a Space with the *Docker* SDK, push this repo, and add the YAML header
  `sdk: docker` and `app_port: 8000` at the top of the Space's `README.md` (not needed in the GitHub README).
  Add secrets under *Settings → Variables and secrets*.
- **Cloud Run / Fly.io / Railway:** deploy the image; the platform supplies `$PORT`, which `gunicorn.conf.py`
  already reads. Set `AGRISENSE_BEHIND_PROXY=1`, `AGRISENSE_ENV=production` and `SITE_URL`.
- **A VPS:** run the container (or `gunicorn app:app`) behind nginx/Caddy for HTTPS, with
  `AGRISENSE_BEHIND_PROXY=1`.

> The Dockerfile follows standard practice but was not built in the environment where this guide was
> prepared (no Docker available there); the identical gunicorn command was exercised directly.

---

## Operations

- **Logs:** Render → service → *Logs*. The app logs to stdout; errors never expose stack traces to visitors.
- **Health:** `/api/health` returns 200 when models are loaded (503 otherwise) — Render uses it as the
  health check.
- **Rollback:** Render → *Deploys* → pick an earlier deploy → *Rollback*.
- **Updating data/models:** retraining is deliberately a manual step (`python -m ml.train_crop_model` …),
  committed as new `models/*.joblib`. Do not change the pinned `scikit-learn` version without retraining —
  the model files are pickles tied to it (Dependabot is configured to leave those pins alone).
- **Rate limits** (per IP, per minute): chat 12, predictions 30, uploads 10, geocoding 40, environment 30,
  revenue 30. The counters live in memory, which is exact for the default single worker; scaling to several
  workers/instances multiplies the effective limit — move to a shared store (e.g. Redis) if you need strict limits.
- **Not included (by design):** database, user accounts, background workers, CDN. Add them only if you need them.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Build fails compiling numpy/pandas/scikit-learn | Python version not pinned. Ensure `PYTHON_VERSION=3.12.7` (in `render.yaml`) and that `.python-version` says `3.12`. |
| Site takes ~1 minute to open | Free instance was asleep. Use an uptime monitor or the paid plan. |
| Chat says "isn't configured" | `LLM_API_KEY` not set in the Render environment (a local `.env` is not deployed). |
| Chat says "Too many requests" | Per-IP rate limit hit (12/min). Wait a minute; adjust in `routes/chat.py` if needed. |
| Sitemap/canonical show `onrender.com` after adding a domain | `SITE_URL` still points at the old address. Update it and redeploy. |
| `/api/health` returns 503 | Models failed to load — check the logs; usually a scikit-learn version mismatch with `models/*.joblib`. |
| Market price "unavailable" | The shared data.gov.in key is rate-limited or no mandi reported that day; set your own `DATA_GOV_IN_API_KEY`. |
| History disappears after a redeploy | Expected on the free tier (ephemeral disk) — see [Data and persistence](#data-and-persistence). |
| Search Console says "Couldn't fetch" for the sitemap | The site was asleep; wake it, re-check `/sitemap.xml` loads, then resubmit. |
