"""
AgriSense AI - AgriSense Assistant chat route

A single, simple endpoint: POST /api/chat. No sessions, no server-side
conversation storage - the frontend resends the structured context
(last prediction + crop plan) and a short recent-turn history with
every request; see services/chat_service.py for why.
"""
from flask import Blueprint, jsonify, request
from utils.ratelimit import rate_limit

from services.chat_service import ask_assistant, ChatServiceError

chat_bp = Blueprint("chat", __name__)

# Error codes that are the CALLER's fault (bad input) vs. the
# assistant/service being unavailable - used to pick the HTTP status.
_CLIENT_ERROR_CODES = {"EMPTY_MESSAGE", "MESSAGE_TOO_LONG"}


@chat_bp.route("/api/chat", methods=["POST"])
@rate_limit("chat", 12, 60)
def chat():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "Invalid request body.", "code": "BAD_REQUEST"}), 400

    message = body.get("message", "")
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    history = body.get("history") if isinstance(body.get("history"), list) else []

    if not isinstance(message, str):
        return jsonify({"error": "Message must be text.", "code": "BAD_REQUEST"}), 400

    try:
        reply = ask_assistant(message, context, history)
        return jsonify({"reply": reply}), 200
    except ChatServiceError as e:
        status = 400 if e.code in _CLIENT_ERROR_CODES else 503
        return jsonify({"error": e.user_message, "code": e.code}), status
