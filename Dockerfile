# AgriSense AI container image.
# Works anywhere that runs Docker: Hugging Face Spaces (Docker SDK), Google Cloud
# Run, Fly.io, Railway, a VPS ...   Render can use it too, but render.yaml uses
# Render's native Python runtime instead (simpler, no Docker needed).
#
#   docker build -t agrisense-ai .
#   docker run --rm -p 8000:8000 --env-file .env agrisense-ai
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    AGRISENSE_ENV=production

# Tesseract enables OCR of soil-report photos (optional; PDF extraction works without it).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as a non-root user; runtime data (caches, per-visitor history) is written to /app/data.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data && chown -R appuser:appuser /app/data
USER appuser

# The platform normally injects $PORT (gunicorn.conf.py reads it); 8000 is the default.
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.getenv('PORT','8000'), timeout=4)" || exit 1

CMD ["gunicorn", "app:app"]
