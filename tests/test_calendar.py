"""
Tests for Feature 2 (Crop Calendar): services/calendar_service.py,
routes/calendar.py.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from services.calendar_service import get_crop_calendar


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ---------------------------------------------------------------------------
# Valid sowing date + verified duration -> harvest window
# ---------------------------------------------------------------------------
def test_valid_sowing_date_gives_harvest_window_for_rice():
    cal = get_crop_calendar("rice", sowing_date="2026-06-15")
    assert cal["sowing_date"] == "2026-06-15"
    assert cal["harvest_window"] is not None
    assert cal["harvest_window"]["start"] == "2026-09-13"  # +90 days
    assert cal["harvest_window"]["end"] == "2026-12-02"    # +170 days


def test_duration_range_reused_verbatim_not_averaged():
    cal = get_crop_calendar("rice")
    assert cal["duration"]["min_days"] == 90
    assert cal["duration"]["max_days"] == 170
    # No invented single-day estimate anywhere in the payload
    assert "expected_maturity_days" not in cal


# ---------------------------------------------------------------------------
# Missing sowing date
# ---------------------------------------------------------------------------
def test_missing_sowing_date_gives_no_harvest_window_but_still_returns_duration():
    cal = get_crop_calendar("rice")
    assert cal["sowing_date"] is None
    assert cal["harvest_window"] is None
    assert cal["duration"]["status"] == "VERIFIED_SOURCE"


def test_unparseable_sowing_date_is_handled_not_crashed():
    cal = get_crop_calendar("rice", sowing_date="not-a-date")
    assert cal["sowing_date"] is None
    assert cal["sowing_date_note"] is not None
    assert cal["harvest_window"] is None


# ---------------------------------------------------------------------------
# Missing duration (e.g. cotton) -> honestly no harvest window
# ---------------------------------------------------------------------------
def test_missing_duration_never_produces_a_harvest_window():
    cal = get_crop_calendar("cotton", sowing_date="2026-06-01")
    assert cal["duration"]["status"] == "UNAVAILABLE"
    assert cal["harvest_window"] is None


# ---------------------------------------------------------------------------
# Day-anchored events (sourced) resolve into real dates when sowing given
# ---------------------------------------------------------------------------
def test_cotton_day_anchored_events_resolve_to_dates():
    cal = get_crop_calendar("cotton", sowing_date="2026-06-01")
    events = cal["day_anchored_events"]
    assert len(events) == 2
    first = events[0]
    assert first["day_offset_min"] == 25
    assert first["date_min"] == "2026-06-26"  # June 1 + 25 days


def test_day_anchored_events_have_no_dates_without_sowing_date():
    cal = get_crop_calendar("cotton")
    events = cal["day_anchored_events"]
    assert len(events) == 2
    assert "date_min" not in events[0]


def test_crop_without_calendar_events_returns_empty_list_not_invented():
    cal = get_crop_calendar("watermelon", sowing_date="2026-06-01")
    assert cal["day_anchored_events"] == []


# ---------------------------------------------------------------------------
# Stage notes reused from existing fertilizer/plant-protection data
# ---------------------------------------------------------------------------
def test_stage_notes_reuse_existing_sourced_fertilizer_stage_text():
    cal = get_crop_calendar("rice")
    assert len(cal["stage_notes"]) > 0
    for note in cal["stage_notes"]:
        assert note["source"] is not None


# ---------------------------------------------------------------------------
# Unsupported / unrecognized crop
# ---------------------------------------------------------------------------
def test_unknown_crop_returns_none():
    assert get_crop_calendar("not_a_real_crop") is None


def test_crop_with_no_agronomy_entry_still_handled_gracefully():
    # Any crop in the master registry but outside crop_agronomy_data.py's
    # explicit list must not crash - it should read as fully UNAVAILABLE.
    cal = get_crop_calendar("watermelon")
    assert cal is not None
    assert cal["duration"]["status"] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Route-level tests
# ---------------------------------------------------------------------------
def test_calendar_route_unknown_crop_404(client):
    resp = client.get("/api/crop-calendar/not_a_real_crop")
    assert resp.status_code == 404


def test_calendar_route_valid_crop_200(client):
    resp = client.get("/api/crop-calendar/rice?sowing_date=2026-06-15")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["harvest_window"] is not None


def test_calendar_route_without_sowing_date_still_200(client):
    resp = client.get("/api/crop-calendar/cotton")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Existing functionality untouched
# ---------------------------------------------------------------------------
def test_existing_endpoints_still_work_alongside_calendar(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/crop-plan/rice").status_code == 200
