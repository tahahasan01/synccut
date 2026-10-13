"""Regression tests for the SSRF and stored-XSS fixes."""

import pytest
from fastapi.testclient import TestClient

from synccut.capture import capture_actions, raster_type
from synccut.core.actions import validate_actions
from synccut.main import app, web_url_or_error
from synccut.netguard import BlockedURL, check_url

BLOCKED = [
    "http://127.0.0.1:8000/api/projects",
    "http://localhost:8000/",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://10.0.0.5/admin",
    "http://192.168.1.1/",
    "http://100.64.0.1/",  # carrier-grade NAT
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",  # IPv4-mapped loopback
    "http://0.0.0.0/",
    "http://app.localhost/",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "ftp://8.8.8.8/",
    "http://user:pass@8.8.8.8/",
]


@pytest.mark.parametrize("url", BLOCKED)
def test_internal_and_non_web_urls_are_blocked(url, monkeypatch):
    monkeypatch.delenv("SYNCCUT_ALLOW_PRIVATE_URLS", raising=False)
    with pytest.raises(BlockedURL):
        check_url(url)


def test_public_ip_is_allowed(monkeypatch):
    monkeypatch.delenv("SYNCCUT_ALLOW_PRIVATE_URLS", raising=False)
    check_url("https://8.8.8.8/")


def test_capture_refuses_internal_page(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNCCUT_ALLOW_PRIVATE_URLS", raising=False)
    actions = validate_actions([{"type": "navigate", "at_ms": 1000, "url": "http://127.0.0.1:8000/api/projects"}], 10_000)
    cap = capture_actions(actions, tmp_path, lambda f, m: None)
    page = next(iter(cap["pages"].values()))
    assert page["status"] == "blocked" and page["image"] is None
    assert "page_unavailable" in cap["results"][actions[0]["id"]]["flags"]
    assert not list(tmp_path.glob("*.jpg"))  # nothing was screenshotted


def test_only_raster_favicons_are_accepted():
    assert raster_type(b"\x89PNG\r\n\x1a\n...") == "png"
    assert raster_type(b"\x00\x00\x01\x00...") == "ico"
    assert raster_type(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>') is None
    assert raster_type(b"<html><script>alert(1)</script></html>") is None


@pytest.mark.parametrize("url", ["javascript:alert(document.cookie)", "data:text/html,<script>alert(1)</script>", "vbscript:x"])
def test_brand_links_must_be_web_urls(url):
    with pytest.raises(ValueError):
        web_url_or_error(url)
    assert web_url_or_error("https://cal.com/me") == "https://cal.com/me"


def test_brand_api_rejects_script_urls():
    client = TestClient(app)
    res = client.put("/api/brand", json={"name": "x", "profile_url": "javascript:alert(1)"})
    assert res.status_code == 422
    res = client.put("/api/brand", json={"name": "x", "portfolio": [{"title": "t", "url": "javascript:alert(1)"}]})
    assert res.status_code == 422


def test_media_is_served_inert():
    res = TestClient(app).get("/media/does-not-exist/file.svg")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in res.headers["content-security-policy"]
    assert "script-src" not in res.headers["content-security-policy"]  # default-src 'none' covers scripts
