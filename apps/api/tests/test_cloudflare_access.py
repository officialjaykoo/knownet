from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))


def test_cloudflare_access_required_blocks_missing_assertion(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRED", "true")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_ALLOWED_EMAILS", "owner@example.com")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRE_JWT", "true")
    with TestClient(app) as client:
        response = client.get("/health/summary")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "cf_access_required"
    get_settings.cache_clear()


def test_cloudflare_access_allows_configured_email(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRED", "true")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_ALLOWED_EMAILS", "owner@example.com")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRE_JWT", "true")
    headers = {
        "cf-access-authenticated-user-email": "owner@example.com",
        "cf-access-jwt-assertion": "test.jwt.assertion",
    }
    with TestClient(app) as client:
        response = client.get("/health/summary", headers=headers)
        assert response.status_code == 200
    get_settings.cache_clear()


def test_cloudflare_access_rejects_wrong_email(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRED", "true")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_ALLOWED_EMAILS", "owner@example.com")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRE_JWT", "false")
    with TestClient(app) as client:
        response = client.get(
            "/health/summary",
            headers={"cf-access-authenticated-user-email": "other@example.com"},
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "cf_access_forbidden"
    get_settings.cache_clear()


def test_public_mode_health_warns_without_cloudflare_access(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("PUBLIC_MODE", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "x" * 40)
    with TestClient(app) as client:
        response = client.get("/health/summary")
        assert response.status_code == 200
        assert "security.public_without_cloudflare_access" in response.json()["data"]["issues"]
    get_settings.cache_clear()
