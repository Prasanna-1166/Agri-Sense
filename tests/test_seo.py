"""
Tests for the SEO / public-page layer (routes/seo.py, templates/*, app.py hooks).

The key rules being protected:
  * sitemap.xml lists exactly the pages that are worth indexing - and every
    crop guide in it is backed by SOURCED data (no thin/placeholder pages);
  * every page has a canonical URL, a sane title/description and valid JSON-LD;
  * unknown URLs return a real 404 (not the app with HTTP 200 = "soft 404").
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from config.crop_agronomy_data import CROP_AGRONOMY, has_agronomy_data
from routes import seo

SITE = "https://agrisense.example"
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
WITH_DATA = sorted(c for c in CROP_AGRONOMY if has_agronomy_data(c))
WITHOUT_DATA = sorted(c for c in CROP_AGRONOMY if not has_agronomy_data(c))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(seo, "SITE_URL", SITE)  # deterministic absolute URLs
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _html(client, path):
    resp = client.get(path)
    return resp, resp.get_data(as_text=True)


def _meta(html, name=None, prop=None):
    attr, val = ("name", name) if name else ("property", prop)
    m = re.search(r'<meta %s="%s" content="([^"]*)"' % (attr, re.escape(val)), html)
    return m.group(1) if m else None


def _jsonld_blocks(html):
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


# --------------------------------------------------------------------------
# robots.txt / sitemap.xml
# --------------------------------------------------------------------------
def test_robots_txt_blocks_api_and_points_to_sitemap(client):
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    body = resp.get_data(as_text=True)
    assert "Disallow: /api/" in body
    assert f"Sitemap: {SITE}/sitemap.xml" in body


def test_sitemap_is_valid_xml_with_absolute_urls(client):
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert resp.mimetype == "application/xml"
    root = ET.fromstring(resp.data)
    locs = [e.text for e in root.findall("sm:url/sm:loc", NS)]
    assert locs, "sitemap is empty"
    assert all(l.startswith(SITE + "/") or l == SITE + "/" for l in locs)
    assert len(locs) == len(set(locs)), "duplicate URLs in sitemap"


def test_sitemap_contains_core_pages_and_every_crop_with_data(client):
    root = ET.fromstring(client.get("/sitemap.xml").data)
    locs = {e.text for e in root.findall("sm:url/sm:loc", NS)}
    assert {f"{SITE}/", f"{SITE}/crops", f"{SITE}/privacy"} <= locs
    for crop in WITH_DATA:
        assert f"{SITE}/crops/{crop}" in locs
    assert len(locs) == 3 + len(WITH_DATA)


def test_sitemap_excludes_crops_without_sourced_data(client):
    """No thin pages: crops with no data, and ML-unsupported crops, are not offered."""
    locs = {e.text for e in ET.fromstring(client.get("/sitemap.xml").data).findall("sm:url/sm:loc", NS)}
    for crop in WITHOUT_DATA + ["groundnut", "wheat", "sugarcane"]:
        assert f"{SITE}/crops/{crop}" not in locs


def test_sitemap_lastmod_values_are_valid_w3c_dates(client):
    root = ET.fromstring(client.get("/sitemap.xml").data)
    for e in root.findall("sm:url/sm:lastmod", NS):
        assert re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", e.text), e.text


def test_sitemap_uses_request_host_when_site_url_unset(monkeypatch):
    monkeypatch.setattr(seo, "SITE_URL", "")
    app = create_app()
    with app.test_client() as c:
        body = c.get("/sitemap.xml", base_url="http://derived.example").get_data(as_text=True)
    assert "<loc>http://derived.example/</loc>" in body


# --------------------------------------------------------------------------
# Home page
# --------------------------------------------------------------------------
def test_home_page_seo_tags(client):
    resp, html = _html(client, "/")
    assert resp.status_code == 200
    assert "<title>AgriSense AI" in html
    desc = _meta(html, name="description")
    assert desc and 50 <= len(desc) <= 160
    assert f'<link rel="canonical" href="{SITE}/">' in html
    assert _meta(html, name="robots") == "index,follow"
    assert _meta(html, prop="og:title") and _meta(html, prop="og:image").startswith(SITE)
    assert _meta(html, prop="og:image").endswith("/static/img/og-image.png")  # stable, unversioned URL
    assert _meta(html, name="twitter:card") == "summary_large_image"
    assert '<html lang="en-IN">' in html


def test_home_page_json_ld_is_valid_and_honest(client):
    _, html = _html(client, "/")
    blocks = _jsonld_blocks(html)
    types = {b["@type"] for b in blocks}
    assert {"WebApplication", "WebSite"} <= types
    app_ld = next(b for b in blocks if b["@type"] == "WebApplication")
    assert app_ld["url"] == f"{SITE}/"
    assert app_ld["offers"]["price"] == "0"
    # Never invent social proof
    assert "aggregateRating" not in app_ld and "review" not in app_ld


def test_home_page_links_to_crawlable_pages_and_has_noscript_fallback(client):
    _, html = _html(client, "/")
    assert 'href="/crops"' in html and 'href="/privacy"' in html
    assert "<noscript>" in html
    assert "CropWise</span>" not in html  # leftover old brand name removed


def test_static_assets_are_versioned_for_cache_busting(client):
    _, html = _html(client, "/")
    assert re.search(r'/static/css/style\.css\?v=[\w.\-]+"', html)


# --------------------------------------------------------------------------
# Crop guides
# --------------------------------------------------------------------------
def test_crops_index_lists_every_guide(client):
    resp, html = _html(client, "/crops")
    assert resp.status_code == 200
    for crop in WITH_DATA:
        assert f'href="/crops/{crop}"' in html
    for crop in WITHOUT_DATA:
        assert f'href="/crops/{crop}"' not in html  # no links to thin pages
    assert f'<link rel="canonical" href="{SITE}/crops">' in html


@pytest.mark.parametrize("crop", WITH_DATA)
def test_every_indexable_crop_page_is_well_formed(client, crop):
    resp, html = _html(client, f"/crops/{crop}")
    assert resp.status_code == 200
    assert _meta(html, name="robots") == "index,follow"
    assert f'<link rel="canonical" href="{SITE}/crops/{crop}">' in html
    desc = _meta(html, name="description")
    assert desc and len(desc) <= 160
    assert html.count("<h1") == 1
    for block in _jsonld_blocks(html):          # all structured data parses
        assert block["@context"] == "https://schema.org"
    crumbs = next(b for b in _jsonld_blocks(html) if b["@type"] == "BreadcrumbList")
    assert [i["position"] for i in crumbs["itemListElement"]] == [1, 2, 3]
    assert "Source:" in html or "Sources" in html   # provenance is visible


def test_crop_page_titles_and_descriptions_are_unique(client):
    titles, descs = set(), set()
    for crop in WITH_DATA:
        _, html = _html(client, f"/crops/{crop}")
        titles.add(re.search(r"<title>(.*?)</title>", html).group(1))
        descs.add(_meta(html, name="description"))
    assert len(titles) == len(WITH_DATA)
    assert len(descs) == len(WITH_DATA)


def test_rice_page_shows_sourced_figures(client):
    _, html = _html(client, "/crops/rice")
    assert "90–170 days" in html
    assert "rarstpt.org" in html                       # link to the real source
    assert "₹66,985" in html                           # surveyed cost, Indian digit grouping
    assert "Stem borer" in html


def test_crop_page_never_claims_more_than_it_has(client):
    """Mango has no verified duration or plant-protection data: the page must say so."""
    _, html = _html(client, "/crops/mango")
    assert "Unavailable" in html
    assert "AgriSense does not list pesticides it cannot source" in html


def test_crop_without_data_is_noindex_and_says_so(client):
    resp, html = _html(client, "/crops/watermelon")
    assert resp.status_code == 200
    assert _meta(html, name="robots") == "noindex,follow"
    assert "No sourced data yet" in html


def test_ml_unsupported_crop_page_is_noindex_and_explains_ml_gap(client):
    resp, html = _html(client, "/crops/groundnut")
    assert resp.status_code == 200
    assert _meta(html, name="robots") == "noindex,follow"
    assert "ML recommendation unavailable" in html


def test_unknown_crop_is_a_real_404(client):
    resp, html = _html(client, "/crops/not-a-crop")
    assert resp.status_code == 404
    assert _meta(html, name="robots") == "noindex,follow"


def test_crop_id_lookup_is_case_insensitive(client):
    assert client.get("/crops/RICE").status_code == 200


# --------------------------------------------------------------------------
# Privacy, manifest, favicon, 404s
# --------------------------------------------------------------------------
def test_privacy_page_discloses_cookie_and_third_parties(client):
    resp, html = _html(client, "/privacy")
    assert resp.status_code == 200
    for term in ("agrisense_vid", "Open-Meteo", "Groq", "no analytics", "deleted from the server"):
        assert term.lower() in html.lower(), term


def test_manifest_is_valid_json_with_icons(client):
    resp = client.get("/site.webmanifest")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["name"] == "AgriSense AI" and data["start_url"] == "/"
    assert {i["sizes"] for i in data["icons"]} == {"192x192", "512x512"}


def test_favicon_redirects_to_static_file_and_assets_exist(client):
    resp = client.get("/favicon.ico")
    assert resp.status_code == 301 and "/static/img/favicon.ico" in resp.headers["Location"]
    for name in ("favicon.svg", "favicon.ico", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "og-image.png"):
        assert client.get(f"/static/img/{name}").status_code == 200, name


def test_unknown_page_returns_real_404_not_the_app(client):
    resp, html = _html(client, "/definitely/not/a/page")
    assert resp.status_code == 404
    assert "Page not found" in html
    assert 'id="sidebar"' not in html            # not the SPA shell
    assert _meta(html, name="robots") == "noindex,follow"


def test_unknown_api_route_still_returns_json_404(client):
    resp = client.get("/api/nope")
    assert resp.status_code == 404 and resp.get_json()["error"]["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def test_json_ld_cannot_break_out_of_its_script_tag():
    out = str(seo._jsonld({"name": "</script><script>alert(1)</script>"}))
    assert "</" not in out
    assert json.loads(out.replace("<\\/", "</"))["name"].startswith("</script>")


@pytest.mark.parametrize("value,expected", [
    (162019.99, "1,62,020"), (66985, "66,985"), (1234567, "12,34,567"), (999, "999"),
    (100000, "1,00,000"), (0, "0"), (None, ""),
])
def test_inr_filter_uses_indian_digit_grouping(value, expected):
    assert seo._inr(value) == expected


@pytest.mark.parametrize("value,expected", [(55.0, "55"), (6.75, "6.75"), (1200, "1,200"), (0.5, "0.5"), (None, "")])
def test_num_filter_is_compact(value, expected):
    assert seo._num(value) == expected


def test_trim_cuts_on_word_boundary():
    out = seo._trim("word " * 60, 40)
    assert len(out) <= 40 and out.endswith("…")


def test_search_console_verification_tags_only_appear_when_configured(monkeypatch):
    app = create_app()
    with app.test_client() as c:
        assert "google-site-verification" not in c.get("/").get_data(as_text=True)
        monkeypatch.setattr(seo, "GOOGLE_SITE_VERIFICATION", "tok_123")
        monkeypatch.setattr(seo, "BING_SITE_VERIFICATION", "bing_456")
        html = c.get("/").get_data(as_text=True)
        assert '<meta name="google-site-verification" content="tok_123">' in html
        assert '<meta name="msvalidate.01" content="bing_456">' in html
