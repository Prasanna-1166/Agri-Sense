"""
Prediction history routes for AgriSense AI

Stores recent predictions locally (simple JSON-file-based storage,
per the "don't introduce a database unless it materially improves
the project" guidance - SQLite would be equivalent complexity here,
so a simple JSON store is used for this lightweight history feature).
"""
import logging
from flask import Blueprint, jsonify, request

from utils.cache import PredictionHistory
from utils.visitor import visitor_path

log = logging.getLogger(__name__)

history_bp = Blueprint("history", __name__)


def _history() -> PredictionHistory:
    """The calling visitor's own history store (see utils/visitor.py) - each
    browser only ever sees and modifies its own predictions."""
    return PredictionHistory(visitor_path("prediction_history.json"))


@history_bp.route("/api/history", methods=["GET"])
def get_history():
    """Get recent prediction history."""
    limit = request.args.get("limit", default=20, type=int)
    limit = max(1, min(limit, 100))

    predictions = _history().get_recent(limit)
    stats = _history().get_stats()

    return jsonify({
        "predictions": list(reversed(predictions)),  # most recent first
        "stats": stats
    }), 200


@history_bp.route("/api/history", methods=["POST"])
def add_history():
    """Add a prediction to history."""
    data = request.get_json(silent=True) or {}

    if not data:
        return jsonify({"error": "No prediction data provided."}), 400

    # Store a condensed version of the prediction. estimated_cost,
    # market_price, estimated_revenue and estimated_gross_margin are
    # OPTIONAL - they typically aren't known yet at the moment the base
    # prediction is saved (crop plan / revenue load asynchronously
    # afterward) and are filled in later via PATCH /api/history/<id>.
    # Records saved before this feature existed simply don't have them -
    # see get_history() / get_farm_summary(), which handle that honestly.
    entry = {
        "id": data.get("prediction_id"),
        "timestamp": data.get("timestamp"),
        "location": data.get("location"),
        "mode": data.get("mode"),
        "recommended_crop": data.get("top_crop", {}).get("crop") if data.get("top_crop") else None,
        "suitability_pct": data.get("top_crop", {}).get("suitability_pct") if data.get("top_crop") else None,
        "estimated_yield": data.get("top_crop", {}).get("predicted_yield_t_per_ha") if data.get("top_crop") else None,
        "farm_area_ha": data.get("farm", {}).get("area_ha"),
        "total_production": data.get("top_crop", {}).get("predicted_total_production_t") if data.get("top_crop") else None,
        "data_quality": data.get("data_quality", {}).get("overall") if data.get("data_quality") else None,
        "estimated_cost": None,
        "market_price_modal_per_quintal": None,
        "market_name": None,
        "estimated_revenue": None,
        "estimated_gross_margin": None,
    }

    success = _history().add(entry)

    if success:
        return jsonify({"status": "saved", "entry": entry}), 201
    else:
        return jsonify({"error": "Failed to save prediction to history."}), 500


@history_bp.route("/api/history/<prediction_id>", methods=["PATCH"])
def patch_history(prediction_id):
    """
    Merge additional fields (estimated_cost, market_price_modal_per_quintal,
    market_name, estimated_revenue, estimated_gross_margin) into an
    existing history entry, once the Crop Plan / Revenue data for that
    prediction has finished loading on the frontend. Only a fixed,
    known set of fields can be patched - arbitrary keys are ignored so
    this can't be used to inject unrelated data into a history record.
    """
    body = request.get_json(silent=True) or {}
    allowed_fields = {
        "estimated_cost", "market_price_modal_per_quintal", "market_name",
        "estimated_revenue", "estimated_gross_margin",
    }
    fields = {k: v for k, v in body.items() if k in allowed_fields}

    if not fields:
        return jsonify({"error": "No recognized fields to update."}), 400

    success = _history().update(prediction_id, fields)
    if success:
        return jsonify({"status": "updated", "id": prediction_id, "fields": fields}), 200
    else:
        return jsonify({"error": "Prediction not found in history."}), 404


@history_bp.route("/api/history/summary", methods=["GET"])
def history_summary():
    """Farm Performance Dashboard summary - aggregated ONLY from fields
    that actually exist in history records; see PredictionHistory.get_farm_summary()."""
    return jsonify(_history().get_farm_summary()), 200


@history_bp.route("/api/history/<prediction_id>", methods=["DELETE"])
def delete_history_item(prediction_id):
    """Delete a specific prediction from history."""
    success = _history().delete(prediction_id)

    if success:
        return jsonify({"status": "deleted", "id": prediction_id}), 200
    else:
        return jsonify({"error": "Prediction not found in history."}), 404


@history_bp.route("/api/history", methods=["DELETE"])
def clear_history():
    """Clear all prediction history."""
    success = _history().clear()

    if success:
        return jsonify({"status": "cleared"}), 200
    else:
        return jsonify({"error": "Failed to clear history."}), 500
