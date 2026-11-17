"""
Tests for Feature 3 (Farm Performance Dashboard): PredictionHistory.update()
and get_farm_summary() in utils/cache.py, plus the PATCH /api/history/<id>
and GET /api/history/summary routes.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        # Start every test with a clean slate
        client.delete("/api/history")
        yield client
        client.delete("/api/history")


def _add_prediction(client, crop, yield_val, area_ha=1.0, prediction_id=None, cost=None, margin=None):
    body = {
        "prediction_id": prediction_id,
        "timestamp": "2026-09-19T10:00:00+00:00",
        "top_crop": {"crop": crop, "suitability_pct": 80, "predicted_yield_t_per_ha": yield_val,
                     "predicted_total_production_t": yield_val * area_ha},
        "farm": {"area_ha": area_ha},
        "mode": "quick",
    }
    resp = client.post("/api/history", json=body)
    entry_id = resp.get_json()["entry"]["id"]
    fields = {}
    if cost is not None:
        fields["estimated_cost"] = cost
    if margin is not None:
        fields["estimated_gross_margin"] = margin
    if fields:
        client.patch(f"/api/history/{entry_id}", json=fields)
    return entry_id


# ---------------------------------------------------------------------------
# Empty / minimal history
# ---------------------------------------------------------------------------
def test_empty_history_summary_says_insufficient_data(client):
    resp = client.get("/api/history/summary")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["insufficient_data"] is True
    assert body["total_predictions"] == 0


def test_one_prediction_summary(client):
    _add_prediction(client, "rice", 4.0, prediction_id="p1")
    body = client.get("/api/history/summary").get_json()
    assert body["insufficient_data"] is False
    assert body["total_predictions"] == 1
    assert body["unique_crops_evaluated"] == 1
    assert body["average_predicted_yield_t_per_ha"] == 4.0
    assert body["latest_recommended_crop"] == "rice"


# ---------------------------------------------------------------------------
# Multiple predictions, multiple crops
# ---------------------------------------------------------------------------
def test_multiple_predictions_multiple_crops(client):
    _add_prediction(client, "rice", 4.0, prediction_id="p1")
    _add_prediction(client, "maize", 5.0, prediction_id="p2")
    _add_prediction(client, "rice", 4.4, prediction_id="p3")
    body = client.get("/api/history/summary").get_json()
    assert body["total_predictions"] == 3
    assert body["unique_crops_evaluated"] == 2
    assert body["average_predicted_yield_t_per_ha"] == pytest.approx((4.0 + 5.0 + 4.4) / 3, abs=0.01)


# ---------------------------------------------------------------------------
# Average cost / revenue only computed over records that actually have it
# ---------------------------------------------------------------------------
def test_average_cost_only_over_records_with_cost(client):
    _add_prediction(client, "rice", 4.0, prediction_id="p1", cost=50000)
    _add_prediction(client, "maize", 5.0, prediction_id="p2")  # no cost patched
    body = client.get("/api/history/summary").get_json()
    assert body["average_estimated_cost_inr"] == 50000
    assert body["average_estimated_cost_sample_size"] == 1


def test_missing_historical_market_price_does_not_break_summary(client):
    """Old-style records with no revenue/margin fields at all must not crash."""
    _add_prediction(client, "rice", 4.0, prediction_id="p1")
    body = client.get("/api/history/summary").get_json()
    assert body["average_gross_margin_inr"] is None
    assert body["average_gross_margin_sample_size"] == 0


# ---------------------------------------------------------------------------
# Yield trend
# ---------------------------------------------------------------------------
def test_yield_trend_requires_at_least_four_records(client):
    _add_prediction(client, "rice", 4.0, prediction_id="p1")
    _add_prediction(client, "rice", 4.2, prediction_id="p2")
    body = client.get("/api/history/summary").get_json()
    assert body["yield_trend"] is None


def test_yield_trend_detects_upward_direction(client):
    for i, y in enumerate([2.0, 2.0, 5.0, 5.0]):
        _add_prediction(client, "rice", y, prediction_id=f"p{i}")
    body = client.get("/api/history/summary").get_json()
    assert body["yield_trend"] == "up"


def test_yield_trend_detects_stable(client):
    for i, y in enumerate([4.0, 4.0, 4.0, 4.0]):
        _add_prediction(client, "rice", y, prediction_id=f"p{i}")
    body = client.get("/api/history/summary").get_json()
    assert body["yield_trend"] == "stable"


# ---------------------------------------------------------------------------
# PATCH endpoint
# ---------------------------------------------------------------------------
def test_patch_updates_only_allowed_fields(client):
    entry_id = _add_prediction(client, "rice", 4.0, prediction_id="p1")
    resp = client.patch(f"/api/history/{entry_id}", json={
        "estimated_cost": 12345, "some_random_field": "should be ignored",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert "some_random_field" not in body["fields"]
    assert body["fields"]["estimated_cost"] == 12345


def test_patch_unknown_id_returns_404(client):
    resp = client.patch("/api/history/does-not-exist", json={"estimated_cost": 1})
    assert resp.status_code == 404


def test_patch_with_no_recognized_fields_returns_400(client):
    entry_id = _add_prediction(client, "rice", 4.0, prediction_id="p1")
    resp = client.patch(f"/api/history/{entry_id}", json={"unrelated": "x"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Backward compatibility: old-style records without new fields
# ---------------------------------------------------------------------------
def test_history_list_with_old_style_records_does_not_crash(client):
    """A record saved before revenue/cost fields existed (all None) must
    still render/list without error."""
    _add_prediction(client, "rice", 4.0, prediction_id="p1")  # no cost/margin ever patched
    resp = client.get("/api/history?limit=10")
    assert resp.status_code == 200
    record = resp.get_json()["predictions"][0]
    assert record["estimated_cost"] is None
    assert record["market_price_modal_per_quintal"] is None
    assert record["estimated_revenue"] is None
    assert record["estimated_gross_margin"] is None


def test_history_delete_still_works(client):
    entry_id = _add_prediction(client, "rice", 4.0, prediction_id="p1")
    resp = client.delete(f"/api/history/{entry_id}")
    assert resp.status_code == 200
    body = client.get("/api/history/summary").get_json()
    assert body["total_predictions"] == 0


# ---------------------------------------------------------------------------
# Existing functionality untouched
# ---------------------------------------------------------------------------
def test_existing_endpoints_still_work_alongside_dashboard(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/crop-plan/rice").status_code == 200
