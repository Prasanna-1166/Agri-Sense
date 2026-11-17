"""
Tests for the AgriSense Assistant (services/chat_service.py,
routes/chat.py).

The LLM call itself is always mocked - these tests verify AgriSense's
own logic: input validation, context formatting (never inventing a
number that wasn't already in the supplied context), and that every
failure mode degrades to a clean JSON error instead of crashing.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest
import requests as real_requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from services.chat_service import ask_assistant, build_context_block, ChatServiceError


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class _FakeLLMResponse:
    def __init__(self, status_code=200, text="This crop was recommended based on your soil and climate data."):
        self.status_code = status_code
        self._text = text

    @property
    def text(self):
        return self._text

    def json(self):
        return {"choices": [{"message": {"content": self._text}}]}


# ---------------------------------------------------------------------------
# Input validation (never reaches the LLM)
# ---------------------------------------------------------------------------
def test_empty_message_rejected(client):
    resp = client.post("/api/chat", json={"message": "", "context": {}, "history": []})
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "EMPTY_MESSAGE"


def test_whitespace_only_message_rejected(client):
    resp = client.post("/api/chat", json={"message": "   ", "context": {}})
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "EMPTY_MESSAGE"


def test_excessively_long_message_rejected(client):
    resp = client.post("/api/chat", json={"message": "x" * 5000, "context": {}})
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "MESSAGE_TOO_LONG"


def test_missing_body_rejected(client):
    resp = client.post("/api/chat", data="not json", content_type="text/plain")
    assert resp.status_code == 400


def test_non_string_message_rejected(client):
    resp = client.post("/api/chat", json={"message": 12345})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Missing API key -> graceful, non-crashing degradation
# ---------------------------------------------------------------------------
def test_missing_api_key_returns_clean_error_not_crash(client):
    with patch("services.chat_service.LLM_API_KEY", ""):
        resp = client.post("/api/chat", json={"message": "Hello", "context": {}})
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["code"] == "NOT_CONFIGURED"
    assert "api key" not in body["error"].lower() or "key is set" in body["error"].lower()


# ---------------------------------------------------------------------------
# LLM call succeeds
# ---------------------------------------------------------------------------
def test_successful_reply(client):
    with patch("services.chat_service.LLM_API_KEY", "fake-key"):
        with patch("services.chat_service.requests.post", return_value=_FakeLLMResponse()):
            resp = client.post("/api/chat", json={
                "message": "Why was this crop recommended?",
                "context": {"top_crop": {"crop": "rice"}},
                "history": [],
            })
    assert resp.status_code == 200
    assert "reply" in resp.get_json()


# ---------------------------------------------------------------------------
# LLM API failure modes -> clean errors, never a 500 crash
# ---------------------------------------------------------------------------
def test_llm_timeout_handled_gracefully(client):
    with patch("services.chat_service.LLM_API_KEY", "fake-key"):
        with patch("services.chat_service.requests.post", side_effect=real_requests.exceptions.Timeout()):
            resp = client.post("/api/chat", json={"message": "Hello", "context": {}})
    assert resp.status_code == 503
    assert resp.get_json()["code"] == "TIMEOUT"


def test_llm_network_failure_handled_gracefully(client):
    with patch("services.chat_service.LLM_API_KEY", "fake-key"):
        with patch("services.chat_service.requests.post",
                   side_effect=real_requests.exceptions.ConnectionError()):
            resp = client.post("/api/chat", json={"message": "Hello", "context": {}})
    assert resp.status_code == 503
    assert resp.get_json()["code"] == "REQUEST_FAILED"


def test_llm_non_200_handled_gracefully(client):
    with patch("services.chat_service.LLM_API_KEY", "fake-key"):
        with patch("services.chat_service.requests.post", return_value=_FakeLLMResponse(status_code=500, text="boom")):
            resp = client.post("/api/chat", json={"message": "Hello", "context": {}})
    assert resp.status_code == 503
    assert resp.get_json()["code"] == "API_ERROR"
    # Internal error text must never leak to the user
    assert "boom" not in resp.get_json()["error"]


def test_llm_empty_response_handled_gracefully(client):
    with patch("services.chat_service.LLM_API_KEY", "fake-key"):
        with patch("services.chat_service.requests.post", return_value=_FakeLLMResponse(text="")):
            resp = client.post("/api/chat", json={"message": "Hello", "context": {}})
    assert resp.status_code == 503
    assert resp.get_json()["code"] == "INVALID_RESPONSE"


def test_no_endpoint_crash_on_malformed_context(client):
    """A malformed/unexpected context shape must never crash the route -
    it should just format what it can."""
    with patch("services.chat_service.LLM_API_KEY", "fake-key"):
        with patch("services.chat_service.requests.post", return_value=_FakeLLMResponse()):
            resp = client.post("/api/chat", json={
                "message": "Hello",
                "context": {"top_crop": "not_a_dict", "crop_plan": None},
            })
    assert resp.status_code in (200, 503)  # never 500


# ---------------------------------------------------------------------------
# Context building - the actual anti-fabrication logic
# ---------------------------------------------------------------------------
def test_context_block_with_no_data_says_so_honestly():
    block = build_context_block({})
    assert "no current farm" in block.lower() or "not available" in block.lower()


def test_context_block_includes_supplied_yield_verbatim():
    context = {
        "top_crop": {"crop": "maize", "predicted_yield_t_per_ha": 4.2, "predicted_total_production_t": 8.4},
        "farm": {"area_ha": 2.0},
    }
    block = build_context_block(context)
    assert "maize" in block
    assert "4.2" in block
    assert "8.4" in block
    assert "2.0" in block


def test_context_block_marks_missing_crop_plan_fields_unavailable():
    context = {
        "crop_plan": {
            "crop": "watermelon",
            "ml_recommendation_supported": True,
            "duration": {"status": "UNAVAILABLE"},
            "planting_material": {"status": "UNAVAILABLE"},
            "fertilizers": [],
            "plant_protection": {"status": "UNAVAILABLE"},
            "economics": {"surveyed_total": None},
        }
    }
    block = build_context_block(context)
    assert block.count("UNAVAILABLE") >= 4


def test_context_block_includes_surveyed_cost_when_present():
    context = {
        "crop_plan": {
            "crop": "rice",
            "ml_recommendation_supported": True,
            "duration": {"status": "UNAVAILABLE"},
            "planting_material": {"status": "UNAVAILABLE"},
            "fertilizers": [],
            "plant_protection": [],
            "economics": {
                "surveyed_total": {
                    "total_per_ha": 66985.0, "total_for_farm": 133970.0,
                    "region": "Telangana", "year": "TE 2021-22",
                    "cost_concept": "Total cost", "notes": "",
                }
            },
        }
    }
    block = build_context_block(context)
    assert "66985" in block
    assert "133970" in block


def test_context_block_includes_available_revenue_and_gross_margin():
    context = {
        "revenue": {
            "status": "AVAILABLE",
            "market_price": {"modal_price_per_quintal": 2000, "market": "Warangal", "price_date": "18/09/2026"},
            "gross_revenue_inr": 136000.0,
            "cost_for_farm_inr": 133970.0,
            "gross_margin_inr": 2030.0,
            "gross_margin_label": "Estimated Gross Margin",
        }
    }
    block = build_context_block(context)
    assert "136000" in block
    assert "2030" in block
    assert "Estimated Gross Margin" in block
    assert "net profit" in block.lower()  # explicitly clarifies it is NOT net profit
    assert "Net Profit:" not in block  # never presented as if it were the label itself


def test_context_block_marks_unavailable_revenue_honestly():
    context = {"revenue": {"status": "UNAVAILABLE", "note": "no verified market price found"}}
    block = build_context_block(context)
    assert "UNAVAILABLE" in block
    assert "no verified market price found" in block


def test_context_block_includes_calendar_harvest_window():
    context = {
        "calendar": {
            "sowing_date": "2026-06-15",
            "harvest_window": {"start": "2026-09-13", "end": "2026-12-02"},
            "day_anchored_events": [],
        }
    }
    block = build_context_block(context)
    assert "2026-09-13" in block
    assert "2026-12-02" in block


def test_context_block_includes_farm_history_summary():
    context = {
        "farm_summary": {
            "insufficient_data": False,
            "total_predictions": 5,
            "unique_crops_evaluated": 2,
            "average_predicted_yield_t_per_ha": 4.2,
            "average_predicted_yield_sample_size": 5,
            "yield_trend": "up",
        }
    }
    block = build_context_block(context)
    assert "5" in block
    assert "up" in block.lower()


def test_context_block_ignores_insufficient_farm_history():
    context = {"farm_summary": {"insufficient_data": True, "total_predictions": 1}}
    block = build_context_block(context)
    assert "Farm History Summary" not in block


# ---------------------------------------------------------------------------
# History handling
# ---------------------------------------------------------------------------
def test_history_is_capped_and_sanitized(client):
    long_history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
    with patch("services.chat_service.LLM_API_KEY", "fake-key"):
        with patch("services.chat_service.requests.post", return_value=_FakeLLMResponse()) as mock_post:
            resp = client.post("/api/chat", json={
                "message": "final question", "context": {}, "history": long_history,
            })
    assert resp.status_code == 200
    sent_payload = mock_post.call_args.kwargs["json"]
    # capped to MAX_HISTORY_TURNS (6) + 1 system message + 1 new user message = 8
    assert len(sent_payload["messages"]) <= 8
    assert sent_payload["messages"][0]["role"] == "system"


# ---------------------------------------------------------------------------
# Existing app functionality untouched by the chatbot addition
# ---------------------------------------------------------------------------
def test_existing_endpoints_still_work_alongside_chat(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/crops").status_code == 200
    assert client.get("/api/crop-plan/rice").status_code == 200
