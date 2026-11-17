"""
AgriSense AI - Crop Calendar route

GET /api/crop-calendar/<crop_id>?sowing_date=YYYY-MM-DD (sowing_date optional)
"""
from flask import Blueprint, jsonify, request

from services.calendar_service import get_crop_calendar

calendar_bp = Blueprint("calendar", __name__)


@calendar_bp.route("/api/crop-calendar/<crop_id>", methods=["GET"])
def crop_calendar(crop_id):
    sowing_date = request.args.get("sowing_date") or None
    calendar = get_crop_calendar(crop_id, sowing_date=sowing_date)
    if calendar is None:
        return jsonify({"error": f"Unknown crop: {crop_id}"}), 404
    return jsonify(calendar), 200
