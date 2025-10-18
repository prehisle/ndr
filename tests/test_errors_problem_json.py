from fastapi.testclient import TestClient

from app.main import create_app


def test_http_exception_problem_json():
    app = create_app()
    client = TestClient(app)
    # non-existent node -> 404 with RFC7807 body
    r = client.get("/api/v1/nodes/999999")
    assert r.status_code == 404
    assert r.headers.get("content-type", "").startswith("application/problem+json")
    body = r.json()
    for key in ("type", "title", "status", "detail", "instance", "error_code"):
        assert key in body
    assert body["status"] == 404
    assert body["error_code"] == "not_found"


def test_validation_error_problem_json():
    app = create_app()
    client = TestClient(app)
    # invalid metadata type should trigger 422 Validation Error
    r = client.post(
        "/api/v1/documents",
        json={"title": "x", "metadata": "not-a-dict"},
        headers={"X-User-Id": "u"},
    )
    assert r.status_code == 422
    assert r.headers.get("content-type", "").startswith("application/problem+json")
    body = r.json()
    assert body.get("status") == 422
    assert body.get("error_code") == "validation_error"
    assert isinstance(body.get("detail"), list)
