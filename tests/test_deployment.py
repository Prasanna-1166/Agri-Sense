"""
Tests for production-readiness behaviour: per-visitor data isolation, rate
limiting, security headers, reverse-proxy handling, correct HTTP error codes,
thread-safe history storage, and robust configuration parsing.
"""
import os
import subprocess
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app as app_module
from app import create_app
from config import settings
from utils import ratelimit, visitor
from utils.cache import PredictionHistory

EXPERT = {"N": 60, "P": 40, "K": 45, "temperature": 26, "humidity": 70, "ph": 6.5,
          "rainfall": 200, "area_ha": 2, "irrigation": "partial"}


@pytest.fixture
def make_client():
    """Factory: each call is a separate 'browser' with its own cookie jar."""
    app = create_app()
    app.config["TESTING"] = True
    return lambda: app.test_client()


def _save_prediction(client, crop="rice", pid="p1"):
    return client.post("/api/history", json={
        "prediction_id": pid, "timestamp": "2026-11-01T10:00:00+00:00",
        "top_crop": {"crop": crop, "suitability_pct": 80, "predicted_yield_t_per_ha": 4.0,
                     "predicted_total_production_t": 8.0},
        "farm": {"area_ha": 2.0}, "mode": "quick"})


# --------------------------------------------------------------------------
# Per-visitor isolation (the privacy fix for a public deployment)
# --------------------------------------------------------------------------
def test_visitors_cannot_see_each_others_history(make_client):
    alice, bob = make_client(), make_client()
    assert _save_prediction(alice, "rice", "alice-1").status_code == 201
    assert len(alice.get("/api/history").get_json()["predictions"]) == 1
    assert bob.get("/api/history").get_json()["predictions"] == []
    assert bob.get("/api/history/summary").get_json()["total_predictions"] == 0


def test_a_visitor_cannot_delete_or_clear_anothers_history(make_client):
    alice, bob = make_client(), make_client()
    _save_prediction(alice, "rice", "alice-1")
    bob.delete("/api/history/alice-1")
    bob.delete("/api/history")
    assert len(alice.get("/api/history").get_json()["predictions"]) == 1


def test_visitors_cannot_see_or_delete_each_others_farm_profile(make_client):
    alice, bob = make_client(), make_client()
    alice.get("/")  # first visit sets the cookie
    r = alice.post("/api/farm/profile", json={"state": "Telangana", "district": "Warangal", "area_ha": 3})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert alice.get("/api/farm/profile").get_json()["exists"] is True
    assert bob.get("/api/farm/profile").get_json() == {"exists": False, "profile": None}
    bob.delete("/api/farm/profile")                      # must not touch Alice's profile
    assert alice.get("/api/farm/profile").get_json()["profile"]["district"] == "Warangal"


def test_same_browser_keeps_its_data_across_requests(make_client):
    c = make_client()
    c.get("/")
    _save_prediction(c, "maize", "m1")
    _save_prediction(c, "rice", "m2")
    assert len(c.get("/api/history").get_json()["predictions"]) == 2


def test_first_page_visit_sets_a_hardened_cookie(make_client):
    resp = make_client().get("/")
    cookie = resp.headers.get("Set-Cookie", "")
    assert cookie.startswith("agrisense_vid=")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "Max-Age=31536000" in cookie


def test_secure_flag_is_set_over_https(make_client):
    resp = make_client().get("/", base_url="https://localhost")
    assert "Secure" in resp.headers["Set-Cookie"]


def test_pages_crawlers_and_static_files_get_no_cookie(make_client):
    c = make_client()
    for path in ("/robots.txt", "/sitemap.xml", "/crops", "/crops/rice", "/privacy",
                 "/static/css/style.css", "/api/health"):
        assert "Set-Cookie" not in c.get(path).headers, path


def test_forged_cookie_cannot_escape_the_data_folder(make_client):
    c = make_client()
    c.set_cookie("agrisense_vid", "../../etc/passwd")
    assert _save_prediction(c).status_code == 201
    new_cookie = c.get_cookie("agrisense_vid")
    assert new_cookie is None or new_cookie.value != "../../etc/passwd"
    assert not os.path.exists(os.path.join(settings.DATA_DIR, "etc"))
    for name in os.listdir(settings.USER_DATA_DIR):
        assert visitor._VID_RE.match(name), f"unexpected folder {name}"


def test_reading_history_creates_nothing_on_disk(tmp_path):
    path = tmp_path / "nested" / "history.json"
    h = PredictionHistory(str(path))
    assert h.get_all() == [] and h.get_recent() == []
    assert not path.exists() and not path.parent.exists()


def test_stale_visitor_folders_are_pruned_but_fresh_and_foreign_ones_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(visitor, "USER_DATA_DIR", str(tmp_path))
    old, fresh = "a" * 32, "b" * 32
    for vid in (old, fresh, "not-a-visitor-folder"):
        (tmp_path / vid).mkdir()
        (tmp_path / vid / "prediction_history.json").write_text("{}")
    ancient = time.time() - 200 * 24 * 3600
    os.utime(tmp_path / old / "prediction_history.json", (ancient, ancient))
    assert visitor.prune_stale_visitor_dirs(90) == 1
    assert not (tmp_path / old).exists()
    assert (tmp_path / fresh).exists() and (tmp_path / "not-a-visitor-folder").exists()
    assert visitor.prune_stale_visitor_dirs(0) == 0  # 0 disables cleanup


# --------------------------------------------------------------------------
# Thread-safe, atomic history storage
# --------------------------------------------------------------------------
def test_concurrent_writes_never_lose_or_corrupt_history(tmp_path):
    path = str(tmp_path / "h.json")
    def worker(n):
        for i in range(10):
            assert PredictionHistory(path).add({"id": f"{n}-{i}", "recommended_crop": "rice"})
    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    entries = PredictionHistory(path).get_all()
    assert len(entries) == 80 and len({e["id"] for e in entries}) == 80


def test_history_writes_leave_no_temp_files(tmp_path):
    h = PredictionHistory(str(tmp_path / "h.json"))
    h.add({"id": "1"}); h.update("1", {"estimated_cost": 5}); h.delete("1"); h.clear()
    assert sorted(os.listdir(tmp_path)) == ["h.json"]


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------
@pytest.fixture
def limits_on(monkeypatch):
    monkeypatch.setattr(ratelimit, "RATE_LIMIT_ENABLED", True)
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_chat_is_rate_limited_with_the_error_shape_the_widget_expects(make_client, limits_on):
    c = make_client()
    codes = [c.post("/api/chat", json={"message": ""}).status_code for _ in range(12)]
    assert set(codes) == {400}                      # 12 allowed (rejected on content, not rate)
    blocked = c.post("/api/chat", json={"message": ""})
    assert blocked.status_code == 429
    body = blocked.get_json()
    assert isinstance(body["error"], str) and body["code"] == "RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_prediction_endpoint_is_rate_limited_with_the_same_flat_error_shape(make_client, limits_on):
    c = make_client()
    codes = [c.post("/api/predict/expert", json=EXPERT).status_code for _ in range(30)]
    assert all(code in (200, 503) for code in codes)
    blocked = c.post("/api/predict/expert", json=EXPERT)
    assert blocked.status_code == 429
    body = blocked.get_json()
    assert isinstance(body["error"], str)      # the frontend shows data.error as text
    assert body["code"] == "RATE_LIMITED" and body["retry_after_seconds"] >= 1


def test_rate_limits_are_per_client_ip(make_client, limits_on):
    c = make_client()
    for _ in range(13):
        c.post("/api/chat", json={"message": ""})
    assert c.post("/api/chat", json={"message": ""}).status_code == 429
    other = c.post("/api/chat", json={"message": ""}, environ_overrides={"REMOTE_ADDR": "10.9.9.9"})
    assert other.status_code == 400                 # a different visitor is unaffected


def test_rate_limit_window_expires():
    ratelimit.reset()
    assert [ratelimit.check("x", 2, 1, "ip")[0] for _ in range(3)] == [True, True, False]
    time.sleep(1.1)
    assert ratelimit.check("x", 2, 1, "ip")[0] is True
    ratelimit.reset()


def test_cheap_read_endpoints_are_not_limited(make_client, limits_on):
    c = make_client()
    assert all(c.get("/api/health").status_code in (200, 503) for _ in range(40))
    assert all(c.get("/api/crop-plan/rice").status_code == 200 for _ in range(40))


# --------------------------------------------------------------------------
# Headers, proxy handling, error codes
# --------------------------------------------------------------------------
def test_security_headers_present(make_client):
    for path in ("/", "/crops", "/api/health"):
        h = make_client().get(path).headers
        assert h["X-Content-Type-Options"] == "nosniff", path
        assert h["X-Frame-Options"] == "SAMEORIGIN"
        assert h["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "geolocation=(self)" in h["Permissions-Policy"]


def test_api_responses_are_never_cached(make_client):
    assert make_client().get("/api/health").headers["Cache-Control"] == "no-store"


def test_hsts_only_in_production_over_https(make_client, monkeypatch):
    monkeypatch.setattr(app_module, "IS_PRODUCTION", True)
    c = make_client()
    assert "Strict-Transport-Security" in c.get("/", base_url="https://localhost").headers
    assert "Strict-Transport-Security" not in c.get("/", base_url="http://localhost").headers
    monkeypatch.setattr(app_module, "IS_PRODUCTION", False)
    assert "Strict-Transport-Security" not in c.get("/", base_url="https://localhost").headers


def test_proxy_headers_are_trusted_only_when_configured(monkeypatch):
    monkeypatch.setattr("routes.seo.SITE_URL", "")
    spoof = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "real.example"}

    monkeypatch.setattr(app_module, "BEHIND_PROXY", True)
    behind = create_app().test_client().get("/sitemap.xml", headers=spoof).get_data(as_text=True)
    assert "<loc>https://real.example/</loc>" in behind

    monkeypatch.setattr(app_module, "BEHIND_PROXY", False)
    direct = create_app().test_client().get("/sitemap.xml", headers=spoof).get_data(as_text=True)
    assert "real.example" not in direct            # spoofable headers ignored when not behind a proxy


def test_wrong_method_is_405_not_a_fake_500(make_client):
    resp = make_client().post("/api/health")
    assert resp.status_code == 405
    assert resp.get_json()["success"] is False


def test_unexpected_exception_returns_clean_json_500(make_client, monkeypatch):
    app = create_app()
    app.config["PROPAGATE_EXCEPTIONS"] = False
    def boom(): raise RuntimeError("secret internal detail")
    app.add_url_rule("/api/_boom", "boom", boom)
    resp = app.test_client().get("/api/_boom")
    assert resp.status_code == 500
    assert "secret internal detail" not in resp.get_data(as_text=True)


# --------------------------------------------------------------------------
# Configuration robustness
# --------------------------------------------------------------------------
def test_blank_or_invalid_env_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("X_TEST_STR", "   ")
    monkeypatch.setenv("X_TEST_INT", "not-a-number")
    assert settings._env("X_TEST_STR", "dflt") == "dflt"
    assert settings._env("X_TEST_UNSET", "dflt") == "dflt"
    assert settings._env_int("X_TEST_INT", 7) == 7
    monkeypatch.setenv("X_TEST_INT", " 12 ")
    assert settings._env_int("X_TEST_INT", 7) == 12


def test_app_starts_without_python_dotenv_installed():
    """A hosting platform may not have python-dotenv: settings must import anyway."""
    code = ("import sys; sys.modules['dotenv'] = None; import config.settings, app; "
            "print('started ok')")
    env = dict(os.environ, AGRISENSE_DATA_DIR=settings.DATA_DIR)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "started ok" in out.stdout
