"""
AgriSense AI - Market price service

Wraps the official Government of India Open Government Data (OGD)
Platform resource "Current Daily Price of Various Commodities from
Various Markets (Mandi)" (sourced from AGMARKNET):
    https://data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi
    Resource ID: 9ef84268-d588-465a-a308-a864a43d0070
    API base:    https://api.data.gov.in/resource/<resource_id>

This is an OPTIONAL data source: if the API is unreachable, the
commodity has no mapped AGMARKNET name, or no record is found, this
module returns a clear UNAVAILABLE result - it never fabricates a
price, and a failure here must never break crop recommendation, yield
prediction, or crop planning (those don't depend on this module at all).

Caching: results are cached (via the same SimpleCache used elsewhere in
this project, e.g. weather_service.py) so the same commodity/state/
district combination is not re-fetched from the external API on every
UI section that needs it (revenue, dashboard, history, chatbot all
reuse this one call path).
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from config.settings import (
    DATA_GOV_IN_API_KEY, DATA_GOV_IN_BASE_URL, MARKET_PRICE_TIMEOUT, CACHE_DIR,
)
from config.commodity_master import get_commodity_names
from utils.cache import SimpleCache

log = logging.getLogger(__name__)

# Mandi prices are typically updated once a day - a 6-hour cache avoids
# hammering the shared/rate-limited API without serving badly stale data.
_cache = SimpleCache(CACHE_DIR, ttl_seconds=6 * 3600)

_SOURCE = {
    "org": "Directorate of Marketing & Inspection, Ministry of Agriculture and Farmers Welfare "
           "(data sourced from the AGMARKNET portal)",
    "title": "Current Daily Price of Various Commodities from Various Markets (Mandi)",
    "url": "https://data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi",
    "platform": "Open Government Data (OGD) Platform India, data.gov.in",
}


def _unavailable(note: str, commodity_query: Optional[List[str]] = None) -> Dict:
    return {
        "status": "UNAVAILABLE",
        "commodity_query": commodity_query,
        "note": note,
        "source": _SOURCE,
    }


def _fetch_records(commodity_name: str, state: Optional[str], district: Optional[str], limit: int = 20) -> List[Dict]:
    """One call to the data.gov.in resource API for a given commodity
    name, optionally narrowed by state/district. Returns a (possibly
    empty) list of raw records; raises on network/HTTP failure so the
    caller can distinguish 'no data' from 'API broken'."""
    params = {
        "api-key": DATA_GOV_IN_API_KEY,
        "format": "json",
        "limit": limit,
        "filters[commodity]": commodity_name,
    }
    if state:
        params["filters[state]"] = state
    if district:
        params["filters[district]"] = district

    resp = requests.get(DATA_GOV_IN_BASE_URL, params=params, timeout=MARKET_PRICE_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data.get("records", []) or []


def _parse_ddmmyyyy(date_str: str):
    try:
        return datetime.strptime(date_str, "%d/%m/%Y")
    except (ValueError, TypeError):
        return None


def _most_recent(records: List[Dict]) -> Optional[Dict]:
    if not records:
        return None
    dated = [(r, _parse_ddmmyyyy(r.get("arrival_date"))) for r in records]
    dated = [(r, d) for r, d in dated if d is not None]
    if not dated:
        return records[0]
    dated.sort(key=lambda pair: pair[1], reverse=True)
    return dated[0][0]


def get_market_price(crop_id: str, state: Optional[str] = None, district: Optional[str] = None) -> Dict:
    """
    Get a reference market price for a crop, preferring the most local
    match available (district -> state -> national), never fabricating
    a value. Every returned AVAILABLE result includes commodity,
    market, state/district, variety, price date, price type, unit, and
    source - per the "never display a price without its date/source"
    requirement.
    """
    commodity_names = get_commodity_names(crop_id)
    if not commodity_names:
        return _unavailable(f"No AGMARKNET commodity mapping is configured for '{crop_id}' yet.")

    cache_key = f"mandi_{crop_id}_{state or 'any'}_{district or 'any'}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    last_error = None
    for commodity_name in commodity_names:
        # Try progressively broader scopes: district -> state -> national.
        attempts = []
        if state and district:
            attempts.append(("district", state, district))
        if state:
            attempts.append(("state", state, None))
        attempts.append(("national", None, None))

        for scope, s, d in attempts:
            try:
                records = _fetch_records(commodity_name, s, d)
            except requests.exceptions.Timeout:
                last_error = "Market price service timed out."
                continue
            except requests.exceptions.RequestException as e:
                log.warning(f"Market price fetch failed for {commodity_name}: {e}")
                last_error = "Market price service is temporarily unavailable."
                continue
            except (ValueError, KeyError) as e:
                log.warning(f"Market price response parse failed for {commodity_name}: {e}")
                last_error = "Market price service returned an unexpected response."
                continue

            record = _most_recent(records)
            if not record:
                continue  # no records at this scope - try the next one

            try:
                modal = float(record.get("modal_price"))
            except (TypeError, ValueError):
                continue  # record without a usable modal price - keep looking

            min_p = record.get("min_price")
            max_p = record.get("max_price")
            result = {
                "status": "AVAILABLE",
                "commodity": record.get("commodity"),
                "commodity_query": commodity_name,
                "variety": record.get("variety"),
                "market": record.get("market"),
                "state": record.get("state"),
                "district": record.get("district"),
                "match_scope": scope,  # "district" | "state" | "national" - how local this match is
                "price_date": record.get("arrival_date"),
                "modal_price_per_quintal": modal,
                "min_price_per_quintal": float(min_p) if min_p not in (None, "") else None,
                "max_price_per_quintal": float(max_p) if max_p not in (None, "") else None,
                "unit": "INR per quintal",
                "price_type": "Modal (most frequently traded price for that market/day)",
                "source": _SOURCE,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "disclaimer": "This is a reference market price, not a guaranteed selling price. "
                              "Actual prices vary by market, buyer, quality/grade and day.",
            }
            _cache.set(cache_key, result)
            return result

    result = _unavailable(
        last_error or f"No current mandi price record was found for '{crop_id}' "
                       f"({', '.join(commodity_names)}) in the available markets.",
        commodity_query=commodity_names,
    )
    # Cache the miss too (briefly, via the same TTL) so a genuinely
    # unmapped/unreported commodity doesn't get hit repeatedly either.
    _cache.set(cache_key, result)
    return result
