"""
AgriSense AI - Farm profile routes

Optional, local, no-authentication farm profile storage so a returning
user can reuse a saved location/farm size/irrigation/soil setup ("My Farm").
Not required to use the app - Planning Mode works without ever saving one.
"""
import json
import logging
import os
import tempfile

from flask import Blueprint, jsonify, request

from utils.visitor import visitor_path

log = logging.getLogger(__name__)

farm_bp = Blueprint("farm", __name__)


def _profile_path() -> str:
    """The calling visitor's own profile file (see utils/visitor.py)."""
    return visitor_path("farm_profile.json")


def _load_profile():
    path = _profile_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Failed to load farm profile: {e}")
        return None


def _save_profile(data):
    path = _profile_path()
    try:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".profile-", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)  # atomic: never leaves a half-written profile
        return True
    except Exception as e:
        log.warning(f"Failed to save farm profile: {e}")
        return False


@farm_bp.route("/api/farm/profile", methods=["GET"])
def get_farm_profile():
    """Get the saved farm profile, if any. Farm profiles are optional."""
    profile = _load_profile()
    if profile is None:
        return jsonify({"exists": False, "profile": None}), 200
    return jsonify({"exists": True, "profile": profile}), 200


@farm_bp.route("/api/farm/profile", methods=["POST"])
def save_farm_profile():
    """Save (or overwrite) the local farm profile."""
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"error": "No profile data provided."}), 400

    allowed_fields = {
        "location", "state", "district", "area_ha", "irrigation", "water_source",
        "current_crop", "crop_stage", "soil", "growing_season", "previous_crop",
    }
    profile = {k: v for k, v in data.items() if k in allowed_fields}

    success = _save_profile(profile)
    if success:
        return jsonify({"status": "saved", "profile": profile}), 200
    return jsonify({"error": "Could not save farm profile."}), 500


@farm_bp.route("/api/farm/profile", methods=["DELETE"])
def delete_farm_profile():
    """Delete the saved farm profile."""
    path = _profile_path()
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError as e:
            log.warning(f"Failed to delete farm profile: {e}")
            return jsonify({"error": "Could not delete farm profile."}), 500
    return jsonify({"status": "deleted"}), 200
