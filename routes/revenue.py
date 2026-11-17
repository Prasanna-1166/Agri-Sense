"""
AgriSense AI - Revenue & Gross Margin route

GET /api/revenue/<crop_id>

Reuses the SAME reverse-geocoding + state/district matching already
used by routes/location.py (via services/geocoding_service and
config/geography) when lat/lon are given instead of state/district
directly - no duplicate location-resolution logic.
"""
from flask import Blueprint, jsonify, request
from utils.ratelimit import rate_limit

from config.crop_master import get_crop_info
from config.geography import match_state_from_address, match_district_from_address
from services import geocoding_service
from services.revenue_service import get_revenue_estimate

revenue_bp = Blueprint("revenue", __name__)


@revenue_bp.route("/api/revenue/<crop_id>", methods=["GET"])
@rate_limit("revenue", 30, 60)
def revenue(crop_id):
    crop_info = get_crop_info(crop_id)
    if not crop_info:
        return jsonify({"error": f"Unknown crop: {crop_id}"}), 404

    try:
        area_ha = float(request.args.get("area_ha", 1.0))
    except (TypeError, ValueError):
        return jsonify({"error": "area_ha must be a number."}), 400
    if area_ha <= 0:
        return jsonify({"error": "area_ha must be a positive number."}), 400

    production_raw = request.args.get("production_t")
    production_t = None
    if production_raw not in (None, ""):
        try:
            production_t = float(production_raw)
        except ValueError:
            return jsonify({"error": "production_t must be a number."}), 400

    state = request.args.get("state") or None
    district = request.args.get("district") or None

    if not state:
        lat = request.args.get("lat")
        lon = request.args.get("lon")
        if lat and lon:
            try:
                lat_f, lon_f = float(lat), float(lon)
                geo = geocoding_service.reverse_geocode(lat_f, lon_f)
                address = (geo.get("result") or {}).get("address", {})
                state = match_state_from_address(address)
                district = district or match_district_from_address(address)
            except (TypeError, ValueError):
                pass  # bad lat/lon - proceed without location scoping, market price falls back to national

    result = get_revenue_estimate(crop_id, production_t, area_ha, state=state, district=district)
    return jsonify(result), 200
