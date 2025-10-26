from fastapi.testclient import TestClient

from app.main import create_app


def _admin_headers():
    return {"X-User-Id": "admin", "X-Admin-Key": "admin-secret"}


def test_admin_cleanup_endpoint():
    app = create_app()
    client = TestClient(app)

    r = client.post("/api/v1/admin/idempotency/cleanup", headers=_admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert "deleted" in body and isinstance(body["deleted"], int)


def test_admin_self_check_endpoint():
    app = create_app()
    client = TestClient(app)

    r = client.get("/api/v1/admin/self-check", headers=_admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert "database" in body and "alembic" in body and "indexes" in body
    assert "extensions" in body and isinstance(body["extensions"], list)


def test_admin_reindex_analyze_endpoint():
    app = create_app()
    client = TestClient(app)

    r = client.post(
        "/api/v1/admin/reindex",
        headers=_admin_headers(),
        params={"method": "analyze", "tables": ["nodes"]},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload.get("method") == "analyze"
    assert "nodes" in payload.get("executed", [])
