#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgriSense AI - Agricultural Decision-Support Platform
=========================================================

Main Flask application entry point.

This module ONLY loads pre-trained models and wires up routes - it never
retrains models on startup. To train models, run:

    python -m ml.train_crop_model
    python -m ml.train_yield_model

Environment variables (all optional - see .env.example for the full list):
    AGRISENSE_HOST           Host to bind to when run directly (default: 127.0.0.1)
    AGRISENSE_PORT           Port to bind to when run directly (default: 5000)
    AGRISENSE_DEBUG          Set to "1" to enable Flask debug mode (local use only)
    AGRISENSE_ENV            "production" on a real deployment
    AGRISENSE_BEHIND_PROXY   "1" behind Render/Heroku/nginx etc. (trust X-Forwarded-*)
    AGRISENSE_DATA_DIR       Where runtime data lives (default: ./data)
    SITE_URL                 Public URL, used for canonical links and sitemap.xml
    AGRISENSE_FORCE_RETRAIN  Set to "1" to force retraining on startup (not recommended)

Run locally with:
    python app.py
In production the app is served by gunicorn (see gunicorn.conf.py):
    gunicorn app:app
"""
import logging
import os
import sys

from flask import Flask, render_template, jsonify, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from config.settings import (
    FLASK_HOST, FLASK_PORT, FLASK_DEBUG, APP_NAME, APP_VERSION, FORCE_RETRAIN,
    IS_PRODUCTION, BEHIND_PROXY, ASSET_VERSION, USER_DATA_RETENTION_DAYS,
)
from utils.logging_config import setup_logging
from utils.visitor import attach_visitor_cookie, get_visitor_id, prune_stale_visitor_dirs

# Setup logging first
setup_logging()
log = logging.getLogger(__name__)


def _not_found_meta():
    from routes.seo import page_meta
    return page_meta(f"Page not found | {APP_NAME}", "This page does not exist.", request.path,
                     robots="noindex,follow")


def create_app():
    """Application factory for AgriSense AI."""
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB upload limit (soil reports)

    if BEHIND_PROXY:
        # Behind a platform load balancer the TCP peer is the proxy, not the visitor.
        # Trust exactly one proxy hop so request.remote_addr / is_secure / host are real.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    if IS_PRODUCTION:
        # Static URLs carry ?v=<deploy id> (see add_asset_version), so they can be cached long.
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 30 * 24 * 3600

    # Housekeeping: remove anonymous per-visitor data that has been idle too long.
    prune_stale_visitor_dirs(USER_DATA_RETENTION_DAYS)

    # Register blueprints
    from routes.health import health_bp
    from routes.location import location_bp
    from routes.environment import environment_bp
    from routes.prediction import prediction_bp
    from routes.history import history_bp
    from routes.crops import crops_bp
    from routes.soil import soil_bp
    from routes.farm import farm_bp
    from routes.current_farm import current_farm_bp
    from routes.crop_plan import crop_plan_bp
    from routes.chat import chat_bp
    from routes.revenue import revenue_bp
    from routes.calendar import calendar_bp
    from routes.seo import seo_bp, home_meta

    app.register_blueprint(health_bp)
    app.register_blueprint(location_bp)
    app.register_blueprint(environment_bp)
    app.register_blueprint(prediction_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(crops_bp)
    app.register_blueprint(soil_bp)
    app.register_blueprint(farm_bp)
    app.register_blueprint(current_farm_bp)
    app.register_blueprint(crop_plan_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(revenue_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(seo_bp)

    # Frontend route
    @app.route("/")
    def index():
        get_visitor_id()  # mint the anonymous-visitor cookie before any API call fires
        return render_template("index.html", app_name=APP_NAME, app_version=APP_VERSION,
                               seo=home_meta())

    @app.url_defaults
    def add_asset_version(endpoint, values):
        """Append ?v=<deploy id> to /static URLs so browsers pick up new CSS/JS after a
        deploy. Pass v=None explicitly to opt out (e.g. social-card images)."""
        if endpoint == "static" or endpoint.endswith(".static"):
            values.setdefault("v", ASSET_VERSION)

    @app.after_request
    def add_response_headers(response):
        response = attach_visitor_cookie(response)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy",
                                    "geolocation=(self), camera=(), microphone=(), payment=()")
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"  # live data - never cache
        if IS_PRODUCTION and request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    # Global error handlers - never show stack traces to normal users
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({
                "success": False,
                "error": {"code": "NOT_FOUND", "message": "Endpoint not found."}
            }), 404
        # A real 404 (not the app with HTTP 200): search engines treat that as a
        # "soft 404" and would index every random URL as a duplicate of the home page.
        return render_template("404.html", seo=_not_found_meta()), 404

    @app.errorhandler(413)
    def too_large(e):
        return jsonify({
            "success": False,
            "error": {"code": "FILE_TOO_LARGE", "message": "Uploaded file is too large."}
        }), 413

    @app.errorhandler(500)
    def server_error(e):
        log.error(f"Internal server error: {e}")
        return jsonify({
            "success": False,
            "error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred. Please try again."}
        }), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, HTTPException):
            # 400/405/429/... keep their real status instead of becoming a fake 500.
            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "error": {"code": e.name.upper().replace(" ", "_"), "message": e.description},
                }), e.code
            return e
        log.error(f"Unhandled exception: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": {"code": "UNEXPECTED_ERROR", "message": "An unexpected error occurred. Please try again."}
        }), 500

    return app


def check_models_status():
    """Check and report model status at startup without training."""
    from ml.predictor import get_status
    status = get_status()

    log.info("=" * 60)
    log.info(f"{APP_NAME} v{APP_VERSION} - Model Status")
    log.info("=" * 60)
    log.info(f"Crop model loaded:  {status['crop_model_loaded']}")
    log.info(f"Yield model loaded: {status['yield_model_loaded']}")

    if not status["ready"]:
        log.warning("-" * 60)
        log.warning("MODELS NOT READY. Predictions will fail until trained.")
        log.warning("Run these commands to train the models:")
        log.warning("  python -m ml.train_crop_model")
        log.warning("  python -m ml.train_yield_model")
        log.warning("-" * 60)
    else:
        log.info("Models ready for predictions.")

    from config.crop_master import SUPPORTED_CROP_IDS, UNSUPPORTED_CROP_IDS
    log.info(f"Crop Master: {len(SUPPORTED_CROP_IDS)} supported crops, "
              f"{len(UNSUPPORTED_CROP_IDS)} flagged as data-unavailable "
              f"({', '.join(UNSUPPORTED_CROP_IDS)})")
    log.info("=" * 60)

    return status["ready"]


app = create_app()

if __name__ == "__main__":
    if FORCE_RETRAIN:
        log.warning("AGRISENSE_FORCE_RETRAIN=1 detected. Training models now...")
        from ml.train_crop_model import train as train_crop
        from ml.train_yield_model import train as train_yield
        train_crop()
        train_yield()
        from ml.predictor import reload_models
        reload_models()

    check_models_status()

    log.info(f"Starting {APP_NAME} v{APP_VERSION} on http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
