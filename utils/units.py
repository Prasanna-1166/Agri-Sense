"""
AgriSense AI - Unit conversion utilities

One shared place for weight/price unit math, so conversion formulas
are never re-implemented in multiple files (revenue, market price,
crop plan all need kg <-> quintal <-> tonne conversions).

Conventions used across the project:
  - Yield/production: tonnes (t) or tonnes/hectare (t/ha)
  - Seed/fertilizer requirement: kilograms (kg)
  - Mandi/market prices (AGMARKNET/data.gov.in): INR per quintal
"""

KG_PER_QUINTAL = 100.0
KG_PER_TONNE = 1000.0
QUINTAL_PER_TONNE = 10.0


def quintal_to_kg(quintal: float) -> float:
    return quintal * KG_PER_QUINTAL


def kg_to_quintal(kg: float) -> float:
    return kg / KG_PER_QUINTAL


def tonnes_to_kg(tonnes: float) -> float:
    return tonnes * KG_PER_TONNE


def kg_to_tonnes(kg: float) -> float:
    return kg / KG_PER_TONNE


def tonnes_to_quintal(tonnes: float) -> float:
    return tonnes * QUINTAL_PER_TONNE


def quintal_to_tonnes(quintal: float) -> float:
    return quintal / QUINTAL_PER_TONNE


def price_per_quintal_to_per_kg(price_per_quintal: float) -> float:
    return price_per_quintal / KG_PER_QUINTAL


def price_per_kg_to_per_quintal(price_per_kg: float) -> float:
    return price_per_kg * KG_PER_QUINTAL
