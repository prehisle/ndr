from fastapi.testclient import TestClient

from app.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_create_node_invalid_slug_returns_422():
    client = _client()
    # 包含点号会违反 ltree 语法
    resp = client.post(
        "/api/v1/nodes",
        json={"name": "Bad", "slug": "bad.slug"},
        headers={"X-User-Id": "u"},
    )
    assert resp.status_code == 422
    assert resp.headers.get("content-type", "").startswith("application/problem+json")


def test_update_node_invalid_slug_returns_422():
    client = _client()
    # 先创建合法节点
    created = client.post(
        "/api/v1/nodes",
        json={"name": "Root", "slug": "root"},
        headers={"X-User-Id": "u"},
    ).json()
    node_id = created["id"]

    # 使用包含大写字母的 slug，应触发 422
    resp = client.put(
        f"/api/v1/nodes/{node_id}",
        json={"slug": "Bad"},
        headers={"X-User-Id": "u"},
    )
    assert resp.status_code == 422
    assert resp.headers.get("content-type", "").startswith("application/problem+json")
