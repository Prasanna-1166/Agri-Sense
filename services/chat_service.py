"""
AgriSense AI - AgriSense Assistant (simple chatbot service)
==============================================================

Deliberately simple, per project requirements:

    AgriSense structured data  +  LLM API  =  Chatbot

NOT implemented here (on purpose, for this version):
  - RAG / vector database / embeddings
  - LangChain / LangGraph / multi-agent orchestration
  - Fine-tuning or a locally-hosted model
  - Server-side conversation persistence (history is browser-session-only;
    the frontend resends recent turns with each request)

Uses an OpenAI-compatible chat completions API (default: Groq, which
has a free, no-credit-card developer tier - see config/settings.py).
Any other OpenAI-compatible provider works by changing LLM_API_URL/
LLM_MODEL; no provider-specific SDK is used, just plain HTTP via
`requests` (already a project dependency), per the "don't add
unnecessary dependencies" requirement.

The LLM is never the source of numerical agricultural truth. Every
number (yield, seed rate, fertilizer dose, cost, duration) already
exists in AgriSense's own data (ml/predictor.py output and
services/agronomy_service.py's crop plan) and is handed to the model
as plain text context; the model's job is only to explain those
already-computed values in natural language, never to invent new ones.
"""
import logging
from typing import Dict, List, Optional

import requests

from config.settings import LLM_API_KEY, LLM_MODEL, LLM_API_URL, LLM_TIMEOUT_SECONDS

log = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 800
MAX_HISTORY_TURNS = 6  # last N browser-held turns resent for continuity; nothing stored server-side

SYSTEM_PROMPT = """You are the AgriSense Assistant, a simple helper built into the AgriSense AI \
agricultural decision-support application for Andhra Pradesh and Telangana farmers.

Answer using ONLY the "AgriSense Data" block supplied below for any specific number or \
recommendation (crop, predicted yield, expected production, seed/planting-material requirement, \
fertilizer dose, plant-protection guidance, crop duration, cost of cultivation, market price, \
expected revenue, estimated gross margin, crop calendar dates, farm history statistics, or \
soil/weather values). Never invent or estimate your own figure for any of these, even if you \
think you know a plausible value - AgriSense's own sourced data is the only source of truth here.

When discussing revenue or margin, always use the exact term AgriSense gives you (e.g. "Estimated \
Gross Margin") - never call it "profit" or "net profit", since it may not include every real \
farming cost. Make clear that market prices and revenue figures are reference estimates for a \
specific market and date, not a guaranteed selling price.

If the AgriSense Data block marks something as UNAVAILABLE, say plainly that AgriSense does not \
have verified data for it yet, and suggest the user check with their local Krishi Vigyan Kendra \
(KVK) or state agriculture department. Do not fill the gap yourself.

Keep the distinction between a model prediction/estimate and a guaranteed outcome. Say things \
like "AgriSense's model estimates approximately X" or "AgriSense has a sourced estimate of ₹X", \
never "you will get X" or "this will definitely cost ₹X".

For fertilizer and plant-protection questions, relay only what AgriSense Data explicitly states \
(including the source and status). Never suggest a pesticide, dose, or spray interval that isn't \
in the data provided.

Explain agricultural and technical terms (like NPK, N/P2O5/K2O, soil pH) in simple, plain language \
when asked.

If the user asks something outside AgriSense's agricultural scope (i.e. unrelated to farming or \
this app's crop/yield/cost/seed/fertilizer/soil/weather data), politely say it's outside your \
current scope and suggest what AgriSense can help with instead.

Keep replies concise - a few short sentences or a short list, not long essays."""


class ChatServiceError(Exception):
    """Raised for any chat failure the route should turn into a clean,
    non-crashing JSON error. `code` lets the route pick an HTTP status;
    `user_message` is always safe to show directly to the user (never
    leaks internal error details, stack traces, or the API key)."""

    def __init__(self, user_message: str, code: str = "CHAT_ERROR"):
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code


def _status_line(status: Optional[str], detail: str) -> str:
    if status in ("VERIFIED_SOURCE", "SOURCE_ESTIMATE"):
        return detail
    return "UNAVAILABLE (no verified source on file)"


def build_context_block(context: Optional[Dict]) -> str:
    """
    Turn the structured AgriSense data the frontend already has (the
    last prediction response + the last-loaded crop plan) into a plain
    text block for the system prompt. This function does no lookups of
    its own - it only formats what the frontend already fetched from
    AgriSense's real APIs, so there is exactly one source of truth.
    """
    if not context:
        return ("No current farm/prediction data is available in this browser session yet. If the "
                "user asks about their crop, yield, cost, seed, or fertilizer, explain that they "
                "should run an analysis from Farm Location first.")
    if not isinstance(context, dict):
        return "No usable AgriSense data was supplied with this request."

    lines = ["=== AgriSense Data (the ONLY source for any number below; never invent your own) ==="]

    farm = context.get("farm") or {}
    if not isinstance(farm, dict):
        farm = {}
    if farm.get("area_ha") is not None:
        lines.append(f"Farm area: {farm['area_ha']} ha")

    top = context.get("top_crop") or {}
    if not isinstance(top, dict):
        top = {}
    if top.get("crop"):
        lines.append(f"ML-recommended crop: {top['crop']}")
        if top.get("predicted_yield_t_per_ha") is not None:
            lines.append(f"Predicted yield (model estimate): {top['predicted_yield_t_per_ha']} t/ha")
        if top.get("predicted_total_production_t") is not None:
            lines.append(f"Predicted total production: {top['predicted_total_production_t']} t")
        yr = top.get("yield_range_t_per_ha") or {}
        if yr.get("low") is not None and yr.get("high") is not None:
            lines.append(f"Yield range: {yr['low']}-{yr['high']} t/ha")
        limiting = ((top.get("explanation") or {}).get("limiting_factor") or {}).get("text")
        if limiting:
            lines.append(f"Limiting factor AgriSense identified: {limiting}")

    plan = context.get("crop_plan") or {}
    if not isinstance(plan, dict):
        plan = {}
    if plan.get("crop"):
        lines.append(f"--- Crop Plan for {plan['crop']} ---")
        lines.append(f"ML recommendation supported for this crop: {plan.get('ml_recommendation_supported')}")
        if plan.get("ml_support_note"):
            lines.append(f"ML support note: {plan['ml_support_note']}")

        dur = plan.get("duration") or {}
        if dur.get("status") == "VERIFIED_SOURCE":
            lines.append(f"Duration: {dur.get('min_days')}-{dur.get('max_days')} days "
                         f"({dur.get('description', '')})")
        else:
            lines.append("Duration: UNAVAILABLE (no verified source)")

        pm = plan.get("planting_material") or {}
        if pm.get("status") in ("VERIFIED_SOURCE", "SOURCE_ESTIMATE"):
            bit = f"{pm.get('quantity_per_ha')} {pm.get('unit')}/ha"
            if pm.get("quantity_for_farm") is not None:
                bit += f"; {pm.get('quantity_for_farm')} {pm.get('unit')} for this farm's area"
            lines.append(f"Seed/planting material requirement ({pm.get('status')}): {bit}")
        else:
            lines.append("Seed/planting material requirement: UNAVAILABLE (no verified source)")

        ferts = plan.get("fertilizers")
        if isinstance(ferts, list) and ferts:
            any_sourced = False
            for f in ferts:
                if f.get("status") in ("VERIFIED_SOURCE", "SOURCE_ESTIMATE") and (
                        f.get("quantity_per_ha") is not None or f.get("quantity_per_plant") is not None):
                    any_sourced = True
                    if f.get("quantity_per_ha") is not None:
                        bit = f"{f.get('quantity_per_ha')} {f.get('unit')}/ha"
                    else:
                        bit = f"{f.get('quantity_per_plant')} {f.get('unit_per_plant')}"
                    lines.append(f"Fertilizer - {f.get('nutrient') or f.get('name')}: {bit} "
                                 f"(stage: {f.get('stage') or 'n/a'}, status: {f.get('status')})")
            if not any_sourced:
                lines.append("Fertilizer recommendation: UNAVAILABLE (no verified source)")
        else:
            lines.append("Fertilizer recommendation: UNAVAILABLE (no verified source)")

        pp = plan.get("plant_protection")
        if isinstance(pp, list) and pp:
            for p in pp[:5]:
                lines.append(f"Plant protection - {p.get('target')}: {p.get('management')}")
        else:
            lines.append("Plant protection: UNAVAILABLE (no verified source on file)")

        econ = plan.get("economics") or {}
        survey = econ.get("surveyed_total")
        if survey:
            lines.append(f"Cost of cultivation (reported survey figure): Rs {survey.get('total_per_ha')}/ha "
                         f"in {survey.get('region')}, {survey.get('year')} "
                         f"(cost concept: {survey.get('cost_concept')}); "
                         f"for this farm's area: Rs {survey.get('total_for_farm')}. "
                         f"{survey.get('notes', '')}")
        else:
            lines.append("Cost of cultivation: UNAVAILABLE (no verified current price data for this crop)")

    revenue = context.get("revenue")
    if isinstance(revenue, dict) and revenue.get("status") == "AVAILABLE":
        market = revenue.get("market_price") or {}
        lines.append("--- Revenue & Return ---")
        lines.append(f"Reference market price (modal): Rs {market.get('modal_price_per_quintal')}/quintal "
                     f"at {market.get('market')} ({market.get('price_date')}), source: AGMARKNET/data.gov.in")
        lines.append(f"Expected gross revenue: Rs {revenue.get('gross_revenue_inr')}")
        if revenue.get("gross_margin_inr") is not None:
            lines.append(f"Estimated cultivation cost used: Rs {revenue.get('cost_for_farm_inr')}")
            lines.append(f"{revenue.get('gross_margin_label')}: Rs {revenue.get('gross_margin_inr')} "
                         f"(this is a GROSS margin, not net profit - not all real costs may be included)")
        else:
            lines.append("Gross margin: UNAVAILABLE (no verified cultivation-cost figure for this crop)")
    elif isinstance(revenue, dict):
        lines.append(f"--- Revenue & Return --- UNAVAILABLE: {revenue.get('note') or 'no verified market price found'}")

    calendar = context.get("calendar")
    if isinstance(calendar, dict):
        lines.append("--- Crop Calendar ---")
        if calendar.get("sowing_date"):
            lines.append(f"Sowing date: {calendar['sowing_date']}")
        if calendar.get("harvest_window"):
            lines.append(f"Estimated harvest window: {calendar['harvest_window']['start']} to "
                         f"{calendar['harvest_window']['end']}")
        else:
            lines.append("Harvest window: UNAVAILABLE (needs both a sowing date and a verified duration)")
        for e in (calendar.get("day_anchored_events") or [])[:5]:
            date_bit = f" ({e.get('date_min')} to {e.get('date_max')})" if e.get("date_min") else ""
            lines.append(f"Calendar event - {e.get('label')}: {e.get('day_offset_min')}-{e.get('day_offset_max')} "
                         f"days after sowing{date_bit}")

    farm_history = context.get("farm_summary")
    if isinstance(farm_history, dict) and not farm_history.get("insufficient_data"):
        lines.append("--- Farm History Summary ---")
        lines.append(f"Total predictions made: {farm_history.get('total_predictions')}")
        lines.append(f"Unique crops evaluated: {farm_history.get('unique_crops_evaluated')}")
        if farm_history.get("average_predicted_yield_t_per_ha") is not None:
            lines.append(f"Average predicted yield across {farm_history.get('average_predicted_yield_sample_size')} "
                         f"record(s): {farm_history.get('average_predicted_yield_t_per_ha')} t/ha")
        if farm_history.get("yield_trend"):
            lines.append(f"Recent yield trend: {farm_history.get('yield_trend')}")
        if farm_history.get("average_gross_margin_inr") is not None:
            lines.append(f"Average estimated gross margin across "
                         f"{farm_history.get('average_gross_margin_sample_size')} record(s): "
                         f"Rs {farm_history.get('average_gross_margin_inr')}")

    env = context.get("environment") or {}
    if not isinstance(env, dict):
        env = {}
    if env:
        env_bits = [f"{k}: {v}" for k, v in env.items() if v is not None]
        if env_bits:
            lines.append("--- Environment ---")
            lines.append(", ".join(env_bits))

    return "\n".join(lines)


def ask_assistant(message: str, context: Optional[Dict], history: Optional[List[Dict]]) -> str:
    """
    Send one chat turn to the LLM. Raises ChatServiceError (never lets
    an unhandled exception escape) for every failure mode: missing API
    key, empty/too-long message, network failure, timeout, or a bad
    response shape.
    """
    if not message or not message.strip():
        raise ChatServiceError("Please enter a message.", code="EMPTY_MESSAGE")

    if len(message) > MAX_MESSAGE_LENGTH:
        raise ChatServiceError(
            f"Message is too long (max {MAX_MESSAGE_LENGTH} characters). Please shorten it.",
            code="MESSAGE_TOO_LONG",
        )

    if not LLM_API_KEY:
        raise ChatServiceError(
            "The AgriSense Assistant isn't configured yet - no LLM API key is set for this "
            "installation. Every other AgriSense feature works without one.",
            code="NOT_CONFIGURED",
        )

    system_prompt = SYSTEM_PROMPT + "\n\n" + build_context_block(context)

    messages: List[Dict] = [{"role": "system", "content": system_prompt}]
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        role = turn.get("role") if isinstance(turn, dict) else None
        content = turn.get("content") if isinstance(turn, dict) else None
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": str(content)[:MAX_MESSAGE_LENGTH]})
    messages.append({"role": "user", "content": message.strip()})

    try:
        resp = requests.post(
            LLM_API_URL,
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "max_tokens": 500,
                "messages": messages,
            },
            timeout=LLM_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout:
        log.warning("AgriSense Assistant: LLM request timed out")
        raise ChatServiceError(
            "The AgriSense Assistant is temporarily unavailable (request timed out). Please try "
            "again later.", code="TIMEOUT",
        )
    except requests.exceptions.RequestException as e:
        log.warning(f"AgriSense Assistant: LLM request failed: {e}")
        raise ChatServiceError(
            "The AgriSense Assistant is temporarily unavailable. Please try again later.",
            code="REQUEST_FAILED",
        )

    if resp.status_code != 200:
        log.warning(f"AgriSense Assistant: LLM API returned {resp.status_code}: {resp.text[:300]}")
        raise ChatServiceError(
            "The AgriSense Assistant is temporarily unavailable. Please try again later.",
            code="API_ERROR",
        )

    try:
        data = resp.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        if not text:
            raise ValueError("empty text in LLM response")
        return text
    except (ValueError, AttributeError, TypeError, IndexError, KeyError) as e:
        log.warning(f"AgriSense Assistant: unexpected LLM response shape: {e}")
        raise ChatServiceError(
            "The AgriSense Assistant is temporarily unavailable. Please try again later.",
            code="INVALID_RESPONSE",
        )
