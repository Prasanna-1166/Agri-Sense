"""
AgriSense AI - Crop Calendar service

Extends the EXISTING crop duration and agronomy data (config/
crop_agronomy_data.py) into a simple timeline - it adds no new
agricultural facts of its own. Three kinds of information, all reused:

  1. Harvest window: sowing date + verified duration range (pure date
     arithmetic on an already-sourced number - only shown when both a
     sowing date AND a VERIFIED_SOURCE duration exist).
  2. Day-anchored events: a handful of crops have day-since-sowing
     figures already documented in their fertilizer/plant-protection
     text (see crop_agronomy_data.py `calendar_events`) - these become
     real calendar dates when a sowing date is given.
  3. Stage notes: the existing fertilizer/plant-protection "stage"
     text (already sourced, already shown on the Crop Plan page) is
     resurfaced here as an unscheduled, qualitative list - never
     assigned a day number unless one already existed in the source.

No new crop stages, day counts, or agronomic claims are invented here.
"""
from datetime import datetime, timedelta
from typing import Dict, Optional

from config.crop_agronomy_data import get_crop_agronomy
from config.crop_master import get_crop_info

DISCLAIMER = (
    "Calendar dates are estimates based on sourced crop-duration ranges and agronomic stage "
    "information. Actual timing varies by variety, sowing method, weather, and management practice."
)


def _parse_date(date_str: Optional[str]):
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def get_crop_calendar(crop_id: str, sowing_date: Optional[str] = None) -> Optional[Dict]:
    """
    Build the crop calendar for one crop. Returns None only if the crop
    is not recognized at all by the Crop Master registry.
    """
    crop_id = crop_id.lower()
    crop_info = get_crop_info(crop_id)
    if not crop_info:
        return None

    agronomy = get_crop_agronomy(crop_id) or {}
    duration = agronomy.get("duration", {"status": "UNAVAILABLE", "note": "No duration data on file."})
    sowing_dt = _parse_date(sowing_date)

    harvest_window = None
    if sowing_dt and duration.get("status") == "VERIFIED_SOURCE":
        harvest_window = {
            "start": (sowing_dt + timedelta(days=duration["min_days"])).isoformat(),
            "end": (sowing_dt + timedelta(days=duration["max_days"])).isoformat(),
        }

    events = []
    for e in agronomy.get("calendar_events", []) or []:
        item = dict(e)
        if sowing_dt:
            item["date_min"] = (sowing_dt + timedelta(days=e["day_offset_min"])).isoformat()
            item["date_max"] = (sowing_dt + timedelta(days=e["day_offset_max"])).isoformat()
        events.append(item)

    stage_notes = []
    for f in agronomy.get("fertilizers", []) or []:
        if isinstance(f, dict) and f.get("stage") and f.get("status") in ("VERIFIED_SOURCE", "SOURCE_ESTIMATE"):
            stage_notes.append({
                "type": "fertilizer",
                "label": f.get("nutrient") or f.get("name"),
                "stage_description": f["stage"],
                "source": f.get("source"),
            })
    pp = agronomy.get("plant_protection")
    if isinstance(pp, list):
        for p in pp:
            if p.get("stage"):
                stage_notes.append({
                    "type": "plant_protection",
                    "label": p.get("target"),
                    "stage_description": p["stage"],
                    "source": p.get("source"),
                })

    return {
        "crop": crop_id,
        "display_name": crop_info.get("display_name", crop_id.capitalize()),
        "sowing_date": sowing_dt.isoformat() if sowing_dt else None,
        "sowing_date_note": None if sowing_dt or not sowing_date else "Could not parse sowing_date; expected YYYY-MM-DD.",
        "duration": duration,
        "harvest_window": harvest_window,
        "day_anchored_events": events,
        "stage_notes": stage_notes,
        "disclaimer": DISCLAIMER,
    }
