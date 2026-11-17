"""
AgriSense AI - Revenue & Gross Margin estimation service

    Expected revenue = predicted production x reference market price
    Estimated gross margin = expected revenue - estimated cultivation cost

Reuses, rather than duplicates:
  - production figures from ml/predictor.py's prediction output (passed
    in by the caller - this module does no ML of its own)
  - cost figures from services/agronomy_service.py's crop plan (the
    same surveyed_total / itemized components already built for the
    Crop Plan & Economics page)
  - price figures from services/market_price_service.py

Terminology discipline (per project requirement): the result is never
called "net profit" or "profit" - costs like labour, land rent,
machinery depreciation, irrigation, transport, and interest are not
all captured by the underlying cost data, so the result is always
"Estimated Gross Margin" (or left unavailable when cost data doesn't
exist at all for a crop).
"""
from typing import Dict, Optional

from services import market_price_service
from services.agronomy_service import get_crop_plan
from utils.units import price_per_quintal_to_per_kg, tonnes_to_kg

DISCLAIMER = (
    "Revenue and gross-margin figures are estimates based on the selected market reference price, "
    "predicted production, and available cost data. Actual selling prices, yield and farm expenses "
    "may vary."
)


def _extract_cost_for_farm(economics: Dict):
    """Prefer a real surveyed cost-of-cultivation total (rice/maize/cotton
    today); fall back to the itemized bottom-up total (currently always
    unpriced/None for every crop - see agronomy_service.py). Returns
    (cost_for_farm_or_None, cost_source_label_or_None)."""
    survey = economics.get("surveyed_total")
    if survey and survey.get("total_for_farm") is not None:
        return survey["total_for_farm"], "surveyed_cost_of_cultivation"
    if economics.get("total_for_farm") is not None:
        return economics["total_for_farm"], "itemized_components"
    return None, None


def get_revenue_estimate(
    crop_id: str,
    production_t: Optional[float],
    area_ha: float,
    state: Optional[str] = None,
    district: Optional[str] = None,
) -> Dict:
    """
    Build the revenue/gross-margin estimate for one crop. Never raises -
    every failure mode (no price, no cost, no production) degrades to an
    honest UNAVAILABLE field rather than a fabricated number or a crash.
    """
    market = market_price_service.get_market_price(crop_id, state=state, district=district)
    plan = get_crop_plan(crop_id, area_ha)
    economics = (plan or {}).get("economics", {})
    cost_for_farm, cost_source = _extract_cost_for_farm(economics)

    result = {
        "crop": crop_id,
        "production_t": production_t,
        "market_price": market,
        "cost_for_farm_inr": cost_for_farm,
        "cost_source": cost_source,
        "gross_revenue_inr": None,
        "gross_margin_inr": None,
        "gross_margin_label": None,
        "status": "UNAVAILABLE",
        "note": None,
        "disclaimer": DISCLAIMER,
    }

    if market.get("status") != "AVAILABLE":
        result["note"] = "Revenue estimate cannot be calculated until a verified market price is available."
        return result

    if production_t is None:
        result["note"] = "Revenue estimate cannot be calculated without a predicted production figure."
        return result

    price_per_kg = price_per_quintal_to_per_kg(market["modal_price_per_quintal"])
    production_kg = tonnes_to_kg(production_t)
    gross_revenue = round(price_per_kg * production_kg, 2)

    result["status"] = "AVAILABLE"
    result["gross_revenue_inr"] = gross_revenue

    if cost_for_farm is not None:
        result["gross_margin_inr"] = round(gross_revenue - cost_for_farm, 2)
        result["gross_margin_label"] = "Estimated Gross Margin"
        result["note"] = (
            "This is an estimate based on the available production, market-price and cost data. "
            "Actual returns vary with market price, farm expenses, quality, variety, and selling "
            "conditions. This is a gross margin, not a net profit - it may not include all real "
            "costs such as labour, land rent, machinery depreciation, irrigation, transport, "
            "interest, or post-harvest costs beyond what the cost figure above already covers."
        )
    else:
        result["note"] = (
            "Gross margin cannot be calculated because no verified cultivation-cost figure exists "
            "for this crop yet - revenue alone is shown."
        )

    return result
