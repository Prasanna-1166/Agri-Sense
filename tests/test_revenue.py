"""
Tests for Feature 1 (Revenue & Profit Estimation): utils/units.py,
services/market_price_service.py, services/revenue_service.py,
routes/revenue.py.

All external market-price calls are mocked - these tests verify
AgriSense's own math and its honest failure handling, never a live
AGMARKNET/data.gov.in response.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest
import requests as real_requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from utils import units
from services import market_price_service
from services.revenue_service import get_revenue_estimate


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def isolated_market_cache(tmp_path):
    """Every test gets its own fresh, empty market-price cache so results
    cached by one test (e.g. an intentional UNAVAILABLE from a mocked
    failure) can never leak into and poison a different test's assertions."""
    fresh_cache = market_price_service.SimpleCache(str(tmp_path), ttl_seconds=6 * 3600)
    with patch("services.market_price_service._cache", fresh_cache):
        yield


class _FakeMandiResponse:
    def __init__(self, records=None, status_code=200):
        self._records = records if records is not None else []
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise real_requests.exceptions.HTTPError(f"{self.status_code} error")

    def json(self):
        return {"records": self._records}


def _rice_record(modal="2000", min_p="1900", max_p="2100", date="18/09/2026",
                  market="Warangal", state="Telangana", district="Warangal"):
    return {
        "commodity": "Paddy(Dhan)(Common)", "variety": "Common", "market": market,
        "state": state, "district": district, "arrival_date": date,
        "min_price": min_p, "max_price": max_p, "modal_price": modal,
    }


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------
def test_quintal_kg_roundtrip():
    assert units.quintal_to_kg(1) == 100
    assert units.kg_to_quintal(100) == 1


def test_tonne_kg_roundtrip():
    assert units.tonnes_to_kg(1) == 1000
    assert units.kg_to_tonnes(1000) == 1


def test_price_per_quintal_to_per_kg():
    assert units.price_per_quintal_to_per_kg(2000) == 20
    assert units.price_per_kg_to_per_quintal(20) == 2000


# ---------------------------------------------------------------------------
# Market price service: caching, scope fallback, graceful failure
# ---------------------------------------------------------------------------
def test_unmapped_commodity_is_unavailable_without_any_api_call():
    with patch("services.market_price_service.requests.get") as mock_get:
        result = market_price_service.get_market_price("totally_unknown_crop_xyz")
    assert result["status"] == "UNAVAILABLE"
    mock_get.assert_not_called()


def test_market_price_available_uses_modal_price():
    with patch("services.market_price_service.requests.get",
               return_value=_FakeMandiResponse([_rice_record()])):
        result = market_price_service.get_market_price("rice", state="Telangana", district="Warangal")
    assert result["status"] == "AVAILABLE"
    assert result["modal_price_per_quintal"] == 2000.0
    assert result["market"] == "Warangal"
    assert result["price_date"] == "18/09/2026"
    assert result["source"] is not None


def test_market_price_falls_back_from_district_to_state():
    """No district-level record, but a state-level one exists."""
    call_count = {"n": 0}

    def fake_get(url, params=None, timeout=None):
        call_count["n"] += 1
        if "filters[district]" in params:
            return _FakeMandiResponse([])  # nothing at district level
        return _FakeMandiResponse([_rice_record(market="Hyderabad")])

    with patch("services.market_price_service.requests.get", side_effect=fake_get):
        result = market_price_service.get_market_price("rice", state="Telangana", district="Warangal")
    assert result["status"] == "AVAILABLE"
    assert result["match_scope"] == "state"


def test_market_price_network_failure_is_unavailable_not_crash():
    with patch("services.market_price_service.requests.get",
               side_effect=real_requests.exceptions.ConnectionError()):
        result = market_price_service.get_market_price("rice", state="Telangana")
    assert result["status"] == "UNAVAILABLE"


def test_market_price_timeout_is_unavailable_not_crash():
    with patch("services.market_price_service.requests.get",
               side_effect=real_requests.exceptions.Timeout()):
        result = market_price_service.get_market_price("rice", state="Telangana")
    assert result["status"] == "UNAVAILABLE"


def test_market_price_result_is_cached():
    with patch("services.market_price_service.requests.get",
               return_value=_FakeMandiResponse([_rice_record()])) as mock_get:
        market_price_service.get_market_price("rice", state="Telangana", district="Warangal")
        market_price_service.get_market_price("rice", state="Telangana", district="Warangal")
    # Second call should be served from cache, not hit the network again
    assert mock_get.call_count == 1


def test_no_usable_price_record_is_unavailable():
    """Records exist but none has a parseable modal_price."""
    bad_record = _rice_record(modal="")
    with patch("services.market_price_service.requests.get",
               return_value=_FakeMandiResponse([bad_record])):
        result = market_price_service.get_market_price("rice", state="Telangana")
    assert result["status"] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Revenue calculation
# ---------------------------------------------------------------------------
def test_revenue_calculation_production_times_price():
    with patch("services.market_price_service.requests.get",
               return_value=_FakeMandiResponse([_rice_record(modal="2000")])):
        result = get_revenue_estimate("rice", production_t=6.8, area_ha=2.0, state="Telangana", district="Warangal")
    assert result["status"] == "AVAILABLE"
    # 6.8 t = 6800 kg; price = 2000/100 = 20/kg; revenue = 136000
    assert result["gross_revenue_inr"] == pytest.approx(136000.0)


def test_revenue_gross_margin_uses_surveyed_cost_never_called_profit():
    with patch("services.market_price_service.requests.get",
               return_value=_FakeMandiResponse([_rice_record(modal="2000")])):
        result = get_revenue_estimate("rice", production_t=6.8, area_ha=2.0, state="Telangana", district="Warangal")
    assert result["gross_margin_label"] == "Estimated Gross Margin"
    assert "profit" not in result["gross_margin_label"].lower()
    assert result["cost_source"] == "surveyed_cost_of_cultivation"
    # cost_for_farm at 2ha should be 66985 * 2 = 133970
    assert result["cost_for_farm_inr"] == pytest.approx(133970.0)
    assert result["gross_margin_inr"] == pytest.approx(136000.0 - 133970.0)


def test_revenue_missing_price_does_not_fabricate():
    with patch("services.market_price_service.requests.get",
               side_effect=real_requests.exceptions.ConnectionError()):
        result = get_revenue_estimate("rice", production_t=6.8, area_ha=2.0)
    assert result["status"] == "UNAVAILABLE"
    assert result["gross_revenue_inr"] is None
    assert result["gross_margin_inr"] is None


def test_revenue_missing_production_does_not_fabricate():
    with patch("services.market_price_service.requests.get",
               return_value=_FakeMandiResponse([_rice_record()])):
        result = get_revenue_estimate("rice", production_t=None, area_ha=2.0, state="Telangana", district="Warangal")
    assert result["status"] == "UNAVAILABLE"
    assert "production" in result["note"].lower()


def test_revenue_no_cost_data_still_shows_revenue_alone():
    """Chickpea has no surveyed_total and no priced components - revenue
    should still compute, margin should stay honestly unavailable."""
    fake_record = {
        "commodity": "Bengal Gram(Gram)(Whole)", "variety": "Whole", "market": "Guntur",
        "state": "Andhra Pradesh", "district": "Guntur", "arrival_date": "18/09/2026",
        "min_price": "5000", "max_price": "5500", "modal_price": "5200",
    }
    with patch("services.market_price_service.requests.get",
               return_value=_FakeMandiResponse([fake_record])):
        result = get_revenue_estimate("chickpea", production_t=2.0, area_ha=1.0)
    assert result["status"] == "AVAILABLE"
    assert result["gross_revenue_inr"] is not None
    assert result["gross_margin_inr"] is None
    assert result["cost_for_farm_inr"] is None


def test_negative_or_zero_production_handled_without_crash():
    with patch("services.market_price_service.requests.get",
               return_value=_FakeMandiResponse([_rice_record()])):
        result_zero = get_revenue_estimate("rice", production_t=0.0, area_ha=1.0, state="Telangana", district="Warangal")
        result_neg = get_revenue_estimate("rice", production_t=-1.0, area_ha=1.0, state="Telangana", district="Warangal")
    # 0 production -> 0 revenue (a valid, non-crashing number); negative
    # production is an upstream data problem, but must never crash here.
    assert result_zero["gross_revenue_inr"] == 0
    assert result_neg["gross_revenue_inr"] is not None


# ---------------------------------------------------------------------------
# Route-level tests
# ---------------------------------------------------------------------------
def test_revenue_route_unknown_crop_404(client):
    resp = client.get("/api/revenue/not_a_real_crop?production_t=1&area_ha=1")
    assert resp.status_code == 404


def test_revenue_route_invalid_area_ha_400(client):
    resp = client.get("/api/revenue/rice?production_t=1&area_ha=0")
    assert resp.status_code == 400


def test_revenue_route_invalid_production_400(client):
    resp = client.get("/api/revenue/rice?production_t=notanumber&area_ha=1")
    assert resp.status_code == 400


def test_revenue_route_works_without_production_or_location(client):
    """Revenue endpoint must not require production/location - it should
    degrade gracefully (market price still attempted at national scope)."""
    with patch("services.market_price_service.requests.get",
               return_value=_FakeMandiResponse([_rice_record()])):
        resp = client.get("/api/revenue/rice")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["production_t"] is None
    assert body["status"] == "UNAVAILABLE"  # no production given


# ---------------------------------------------------------------------------
# Existing functionality untouched
# ---------------------------------------------------------------------------
def test_existing_endpoints_still_work_alongside_revenue(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/crop-plan/rice").status_code == 200
