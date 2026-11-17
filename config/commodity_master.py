"""
AgriSense AI - Crop-to-market-commodity name mapping

AGMARKNET/data.gov.in's "Current Daily Price of Various Commodities from
Various Markets (Mandi)" dataset identifies commodities by its own text
names (e.g. "Bengal Gram(Gram)(Whole)", not "chickpea"). This is the ONE
place that maps AgriSense's internal crop_id to the commodity name(s) to
query for - so the mapping is never duplicated in market_price_service.py,
revenue_service.py, or anywhere else.

These names are AGMARKNET's own commonly-used listings; exact spelling in
the live dataset can vary by state/season entry. If a name doesn't match
any current record, market_price_service reports the price as honestly
UNAVAILABLE rather than guessing a different name silently.
"""
from typing import List, Optional

# crop_id -> list of AGMARKNET commodity names to try, in order
CROP_TO_MARKET_COMMODITY = {
    "rice": ["Paddy(Dhan)(Common)", "Rice"],
    "maize": ["Maize"],
    "cotton": ["Cotton"],
    "chickpea": ["Bengal Gram(Gram)(Whole)", "Gram Raw(Chholia)"],
    "blackgram": ["Black Gram (Urd Beans)(Whole)"],
    "mungbean": ["Green Gram (Moong)(Whole)"],
    "pigeonpeas": ["Arhar (Tur/Red Gram)(Whole)"],
    "mango": ["Mango"],
    "banana": ["Banana"],
    "coconut": ["Coconut"],
    "orange": ["Orange"],
    "grapes": ["Grapes"],
    "papaya": ["Papaya"],
    "pomegranate": ["Pomegranate"],
    "apple": ["Apple"],
    "jute": ["Jute"],
    "lentil": ["Lentil (Masur)(Whole)", "Masur Dal"],
    "coffee": ["Coffee"],
    "kidneybeans": ["Rajmash Chuda", "Rajmash"],
    "mothbeans": ["Moth"],
    "muskmelon": ["Musk Melon"],
    "watermelon": ["Water Melon"],
}


def get_commodity_names(crop_id: str) -> Optional[List[str]]:
    """Return the AGMARKNET commodity name(s) to try for a crop_id, or
    None if this crop has no known mapping at all."""
    return CROP_TO_MARKET_COMMODITY.get(crop_id.lower())
