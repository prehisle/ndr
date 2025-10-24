from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.common.config import get_settings
from app.main import create_app

TOKEN_SECRET = "jwt-secret"


def _issue_token(sub: str, *, permissions: list[str] | None = None) -> str:
    payload: dict[str, object] = {
        "sub": sub,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    if permissions is not None:
        payload["permissions"] = permissions
    return jwt.encode(payload, TOKEN_SECRET, algorithm="HS256")


def _setup_auth_environment() -> None:
    os.environ["AUTH_ENABLED"] = "true"
    os.environ["AUTH_TOKEN_SECRET"] = TOKEN_SECRET
    os.environ["AUTH_DEFAULT_PERMISSIONS"] = ""
    os.environ["AUTH_DEFAULT_ROLES"] = ""
    os.environ["AUTH_ALLOW_ANONYMOUS"] = "false"
    os.environ["AUTH_TOKEN_ALGORITHM"] = "HS256"
    os.environ["API_KEY_ENABLED"] = "false"
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _teardown_auth_environment() -> None:
    for key in (
        "AUTH_ENABLED",
        "AUTH_TOKEN_SECRET",
        "AUTH_DEFAULT_PERMISSIONS",
        "AUTH_DEFAULT_ROLES",
        "AUTH_ALLOW_ANONYMOUS",
        "AUTH_TOKEN_ALGORITHM",
        "API_KEY_ENABLED",
    ):
        os.environ.pop(key, None)
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_missing_token_returns_401():
    _setup_auth_environment()
    try:
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/v1/documents")
        assert response.status_code == 401
        body = response.json()
        assert body["error_code"] == "unauthenticated"
    finally:
        _teardown_auth_environment()


def test_missing_permission_returns_403():
    _setup_auth_environment()
    try:
        app = create_app()
        client = TestClient(app)

        token = _issue_token("user-1", permissions=["documents:read"])
        response = client.post(
            "/api/v1/documents",
            json={"title": "A", "metadata": {}, "content": {}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403
        body = response.json()
        assert body["error_code"] == "permission_denied"
        assert body["detail"]["missing_permissions"] == ["documents:write"]
    finally:
        _teardown_auth_environment()


def test_request_succeeds_with_required_permission():
    _setup_auth_environment()
    try:
        app = create_app()
        client = TestClient(app)

        token = _issue_token("user-2", permissions=["documents:write"])
        response = client.post(
            "/api/v1/documents",
            json={"title": "A", "metadata": {}, "content": {}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "A"
        assert body["created_by"] == "user-2"
    finally:
        _teardown_auth_environment()
