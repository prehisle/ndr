import os

from fastapi.testclient import TestClient

from app.common.config import get_settings
from app.main import create_app


def test_api_key_required_when_enabled():
    # Enable API key and set expected key
    os.environ["API_KEY_ENABLED"] = "true"
    os.environ["API_KEY"] = "secret-123"
    # reset settings cache
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = create_app()
    client = TestClient(app)

    # Missing key -> 401 on protected routes
    r = client.post(
        "/api/v1/documents",
        json={"title": "A", "metadata": {}},
        headers={"X-User-Id": "u"},
    )
    assert r.status_code == 401

    # Wrong key -> 401
    r = client.post(
        "/api/v1/documents",
        json={"title": "A", "metadata": {}},
        headers={"X-User-Id": "u", "X-API-Key": "wrong"},
    )
    assert r.status_code == 401

    # Correct key -> 201
    r = client.post(
        "/api/v1/documents",
        json={"title": "A", "metadata": {}},
        headers={"X-User-Id": "u", "X-API-Key": "secret-123"},
    )
    assert r.status_code == 201

    # Clean up: disable API key for subsequent tests
    os.environ["API_KEY_ENABLED"] = "false"
    get_settings.cache_clear()  # type: ignore[attr-defined]
