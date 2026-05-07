import pytest

from knownet_api.config import get_settings


@pytest.fixture(autouse=True)
def isolate_security_env(monkeypatch):
    monkeypatch.setenv("PUBLIC_MODE", "false")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRED", "false")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_ALLOWED_EMAILS", "")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRE_JWT", "true")
    monkeypatch.setenv("KNOWNET_DB_VERSION", "v2")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
