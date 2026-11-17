"""
AgriSense AI - SEO & public-page routes

The main app is a single-page dashboard served at "/", which on its own gives
search engines exactly one URL to index. This blueprint adds the crawlable
surface around it:

    /robots.txt         crawl rules + sitemap location
    /sitemap.xml        every indexable page, generated from live data
    /crops              index of crop guides
    /crops/<crop_id>    one server-rendered guide per crop that has SOURCED data
    /privacy            plain-language privacy notice
    /site.webmanifest   installable-app metadata
    /favicon.ico        legacy favicon location

Honesty rule (same as the rest of the project): a crop guide is only
indexable if AgriSense actually holds sourced data for it. Crops without data
are kept out of the sitemap and marked `noindex` - no thin or placeholder
pages are offered to search engines. All numbers come from
services/agronomy_service.get_crop_plan(), i.e. the one source of truth that
also feeds the app and the chatbot; nothing is duplicated here.
"""
import json
from typing import Dict, List, Optional

from flask import (Blueprint, Response, abort, redirect, render_template,
                   request, url_for)
from markupsafe import Markup

from config.crop_agronomy_data import CROP_AGRONOMY, has_agronomy_data
from config.crop_master import CROP_MASTER, get_crop_info
from config.settings import (APP_DESCRIPTION, APP_NAME, BING_SITE_VERIFICATION,
                             GOOGLE_SITE_VERIFICATION, SITE_URL)
from services.agronomy_service import get_crop_plan

seo_bp = Blueprint("seo", __name__)

REPO_URL = "https://github.com/Prasanna-1166/AgriSense-AI"
PRIVACY_UPDATED = "2026-11"  # W3C date (YYYY-MM) - bump when privacy.html changes
DEFAULT_OG_IMAGE = "img/og-image.png"

HOME_TITLE = "AgriSense AI – Smart Crop Recommendation for AP & Telangana"
HOME_DESCRIPTION = (
    "Free crop advisor for Andhra Pradesh & Telangana farms: ML crop recommendation, "
    "yield estimate, seed and fertilizer plan, cost and market-price returns."
)


# --------------------------------------------------------------------------
# URL helpers
# --------------------------------------------------------------------------
def site_url() -> str:
    """Public base URL with no trailing slash. SITE_URL wins (stable canonical
    URLs even if the site is reachable on several hostnames); otherwise it is
    derived from the request, which is correct behind a proxy when
    AGRISENSE_BEHIND_PROXY=1."""
    return SITE_URL or request.url_root.rstrip("/")


def absolute(path: str) -> str:
    return site_url() + (path if path.startswith("/") else "/" + path)


def static_absolute(filename: str) -> str:
    # v=None: social-card images keep a stable URL across deploys
    return absolute(url_for("static", filename=filename, v=None))


def _jsonld(obj) -> Markup:
    """JSON-LD for a <script> tag. '</' is escaped so data can never close the tag."""
    return Markup(json.dumps(obj, ensure_ascii=False).replace("</", "<\\/"))


# --------------------------------------------------------------------------
# Page metadata (shared by templates/_head_meta.html)
# --------------------------------------------------------------------------
def _trim(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def page_meta(title: str, description: str, path: str, *, robots: str = "index,follow",
              og_type: str = "website", json_ld: Optional[List[dict]] = None) -> Dict:
    """Everything <head> needs for SEO and social sharing, for one page."""
    return {
        "title": title,
        "description": _trim(description, 160),
        "canonical": absolute(path),
        "robots": robots,
        "og_type": og_type,
        "og_image": static_absolute(DEFAULT_OG_IMAGE),
        "site_name": APP_NAME,
        "google_verification": GOOGLE_SITE_VERIFICATION,
        "bing_verification": BING_SITE_VERIFICATION,
        "json_ld": [_jsonld(x) for x in (json_ld or [])],
    }


def home_meta() -> Dict:
    app_ld = {
        "@context": "https://schema.org",
        "@type": "WebApplication",
        "name": APP_NAME,
        "url": absolute("/"),
        "description": APP_DESCRIPTION,
        "applicationCategory": "Agriculture decision-support",
        "operatingSystem": "Any (web browser)",
        "browserRequirements": "Requires JavaScript",
        "inLanguage": "en-IN",
        "isAccessibleForFree": True,
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "INR"},
        "areaServed": [{"@type": "AdministrativeArea", "name": "Andhra Pradesh"},
                       {"@type": "AdministrativeArea", "name": "Telangana"}],
        "featureList": [
            "Machine-learning crop recommendation from soil and climate inputs",
            "Yield and production estimate for your farm area",
            "Seed, fertilizer and crop-duration reference with named sources",
            "Cultivation cost, mandi market price and gross-margin estimate",
            "Crop calendar and prediction history",
        ],
        "sameAs": [REPO_URL],
    }
    site_ld = {"@context": "https://schema.org", "@type": "WebSite", "name": APP_NAME,
               "url": absolute("/"), "inLanguage": "en-IN"}
    return page_meta(HOME_TITLE, HOME_DESCRIPTION, "/", json_ld=[app_ld, site_ld])


# --------------------------------------------------------------------------
# Crop guide helpers
# --------------------------------------------------------------------------
_SOURCED = ("VERIFIED_SOURCE", "SOURCE_ESTIMATE")


def indexable_crop_ids() -> List[str]:
    """Crops that have real sourced data, in a stable (alphabetical) order."""
    return sorted(c for c in CROP_AGRONOMY if c in CROP_MASTER and has_agronomy_data(c))


def _available_facts(plan: Dict) -> List[tuple]:
    """(key, short label) for each kind of sourced info this crop really has."""
    facts = []
    pm = plan.get("planting_material") or {}
    if pm.get("status") in _SOURCED:
        facts.append(("planting", "Seed Rate" if pm.get("type") == "seed" else "Planting Density"))
    ferts = plan.get("fertilizers")
    if isinstance(ferts, list) and any(
            f.get("status") in _SOURCED and (f.get("quantity_per_ha") is not None
                                              or f.get("quantity_per_plant") is not None)
            for f in ferts):
        facts.append(("fertilizer", "Fertilizer"))
    if (plan.get("duration") or {}).get("status") == "VERIFIED_SOURCE":
        facts.append(("duration", "Crop Duration"))
    if (plan.get("economics") or {}).get("surveyed_total"):
        facts.append(("cost", "Cost of Cultivation"))
    if isinstance(plan.get("plant_protection"), list) and plan["plant_protection"]:
        facts.append(("protection", "Plant Protection"))
    return facts


def crop_meta(plan: Dict, crop_id: str, facts: List[tuple]) -> Dict:
    name = plan["display_name"]
    path = f"/crops/{crop_id}"
    labels = [label for _, label in facts]
    if facts:
        title = f"{name} Cultivation Guide: {', '.join(labels[:3])} | {APP_NAME}"
        description = (f"{name} reference data for farmers - {', '.join(l.lower() for l in labels)}. "
                       f"Every figure is shown with its source; scale it to your own farm area with {APP_NAME}.")
        robots = "index,follow"
    else:  # known crop, nothing sourced: usable page, but not for search engines
        title = f"{name} - reference data not yet available | {APP_NAME}"
        description = f"AgriSense AI does not yet hold sourced cultivation data for {name}."
        robots = "noindex,follow"

    breadcrumbs = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": APP_NAME, "item": absolute("/")},
            {"@type": "ListItem", "position": 2, "name": "Crop guides", "item": absolute("/crops")},
            {"@type": "ListItem", "position": 3, "name": name, "item": absolute(path)},
        ],
    }
    webpage = {
        "@context": "https://schema.org", "@type": "WebPage", "name": title, "url": absolute(path),
        "description": _trim(description, 160), "inLanguage": "en-IN",
        "isPartOf": {"@type": "WebSite", "name": APP_NAME, "url": absolute("/")},
        "publisher": {"@type": "Organization", "name": APP_NAME, "url": absolute("/")},
    }
    if plan.get("last_verified"):
        webpage["dateModified"] = plan["last_verified"]
    return page_meta(title, description, path, robots=robots, json_ld=[webpage, breadcrumbs])


# --------------------------------------------------------------------------
# Template filters (registered app-wide)
# --------------------------------------------------------------------------
@seo_bp.app_template_filter("num")
def _num(value, digits: int = 2) -> str:
    """Compact number: 55.0 -> '55', 6.75 -> '6.75', 1200 -> '1,200'."""
    try:
        text = f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "" if value is None else str(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


@seo_bp.app_template_filter("inr")
def _inr(value) -> str:
    """Whole rupees with Indian digit grouping: 162019.99 -> '1,62,020'."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return "" if value is None else str(value)
    sign, digits = ("-" if n < 0 else ""), str(abs(n))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        digits = ",".join(parts) + "," + tail
    return sign + digits


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@seo_bp.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /api/",
        "",
        f"Sitemap: {absolute('/sitemap.xml')}",
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@seo_bp.route("/sitemap.xml")
def sitemap_xml():
    crops = indexable_crop_ids()
    newest = max((CROP_AGRONOMY[c].get("last_verified") or "" for c in crops), default="")

    entries = [("/", newest), ("/crops", newest)]
    entries += [(f"/crops/{c}", CROP_AGRONOMY[c].get("last_verified") or "") for c in crops]
    entries.append(("/privacy", PRIVACY_UPDATED))

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, lastmod in entries:
        out.append("  <url>")
        out.append(f"    <loc>{absolute(path)}</loc>")
        if lastmod:
            out.append(f"    <lastmod>{lastmod}</lastmod>")
        out.append("  </url>")
    out.append("</urlset>")
    return Response("\n".join(out) + "\n", mimetype="application/xml")


@seo_bp.route("/crops")
def crops_index():
    guides = []
    for crop_id in indexable_crop_ids():
        plan = get_crop_plan(crop_id, 1.0)
        guides.append({
            "id": crop_id,
            "name": plan["display_name"],
            "category": (get_crop_info(crop_id) or {}).get("category", "other"),
            "facts": [label for _, label in _available_facts(plan)],
        })
    by_category: Dict[str, list] = {}
    for g in guides:
        by_category.setdefault(g["category"], []).append(g)

    seo = page_meta(
        f"Crop Guides: Seed Rate, Fertilizer & Duration | {APP_NAME}",
        f"Sourced cultivation reference for {len(guides)} crops grown in India - seed or planting "
        f"requirement, fertilizer doses, crop duration and cost - each figure with its source.",
        "/crops",
        json_ld=[{
            "@context": "https://schema.org", "@type": "CollectionPage", "name": "Crop guides",
            "url": absolute("/crops"), "inLanguage": "en-IN",
            "isPartOf": {"@type": "WebSite", "name": APP_NAME, "url": absolute("/")},
        }],
    )
    return render_template("crops_index.html", seo=seo, by_category=by_category, total=len(guides))


@seo_bp.route("/crops/<crop_id>")
def crop_detail(crop_id):
    crop_id = crop_id.lower()
    if not get_crop_info(crop_id):
        abort(404)
    plan = get_crop_plan(crop_id, 1.0)
    facts = _available_facts(plan)
    category = (get_crop_info(crop_id) or {}).get("category")
    related = [c for c in indexable_crop_ids()
               if c != crop_id and (get_crop_info(c) or {}).get("category") == category][:4]
    related_crops = [{"id": c, "name": get_crop_info(c)["display_name"]} for c in related]
    return render_template("crop_detail.html", seo=crop_meta(plan, crop_id, facts), plan=plan,
                           crop_id=crop_id, crop_info=get_crop_info(crop_id), has_facts=bool(facts),
                           related_crops=related_crops)


@seo_bp.route("/privacy")
def privacy():
    seo = page_meta(f"Privacy | {APP_NAME}",
                    "What AgriSense AI does with your location, farm details and chat messages, "
                    "which third-party services it calls, and the one cookie it uses.",
                    "/privacy")
    return render_template("privacy.html", seo=seo, repo_url=REPO_URL)


@seo_bp.route("/site.webmanifest")
def manifest():
    data = {
        "name": APP_NAME, "short_name": "AgriSense", "description": APP_DESCRIPTION,
        "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#F1F4EE", "theme_color": "#1F3D2B",
        "icons": [
            {"src": url_for("static", filename="img/icon-192.png", v=None), "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="img/icon-512.png", v=None), "sizes": "512x512", "type": "image/png"},
        ],
    }
    return Response(json.dumps(data, indent=2), mimetype="application/manifest+json")


@seo_bp.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="img/favicon.ico", v=None), code=301)
