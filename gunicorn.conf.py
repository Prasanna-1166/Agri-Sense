"""
Gunicorn settings for AgriSense AI (picked up automatically by `gunicorn app:app`).

Why ONE worker with several threads:
* The app + ML models use ~215 MB of RAM. Free hosting tiers give 512 MB, so a
  second worker process would not fit; threads share the loaded models.
* The in-memory rate limiter (utils/ratelimit.py) keeps its counters per
  process; a single worker keeps those limits exact.
* The workload is I/O-bound (calls to weather/soil/geocoding/LLM APIs), which
  threads handle well. History/profile file writes are protected by locks.
Raise WEB_CONCURRENCY only on a bigger instance.
"""
import os

# Render, Heroku, Cloud Run etc. tell the app which port to listen on via $PORT.
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

workers = int(os.getenv("WEB_CONCURRENCY", "1"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))

# External APIs can be slow on a cold request; the app's own calls time out first.
timeout = 120
graceful_timeout = 30
keepalive = 5

# Load the app (and the ML models) once, before serving.
preload_app = True

# Log to stdout/stderr so the platform's log viewer shows everything.
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
