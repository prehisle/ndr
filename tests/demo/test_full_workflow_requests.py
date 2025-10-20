import os
import uuid
from typing import Dict

import requests


def _base_url() -> str:
    url = os.getenv("NDR_BASE_URL", "http://localhost:9001")
    return url.rstrip("/")


def _auth_headers(user_id: str) -> Dict[str, str]:
    return {"X-User-Id": user_id}


def _request(method: str, path: str, *, headers=None, params=None, json=None):
    url = f"{_base_url()}{path}"
    resp = requests.request(method, url, headers=headers, params=params, json=json)
    resp.raise_for_status()
    return resp


def test_full_workflow_with_soft_delete_and_restore_requests():
    # --- 创建文档与节点，并建立关系 ---
    doc_resp = _request(
        "POST",
        "/api/v1/documents",
        headers=_auth_headers("author"),
        json={
            "title": "Workflow Doc",
            "metadata": {"stage": "draft"},
            "content": {"body": "initial"},
        },
    )
    document_id = doc_resp.json()["id"]

    node_resp = _request(
        "POST",
        "/api/v1/nodes",
        headers=_auth_headers("author"),
        json={"name": "Workflow Node", "slug": "workflow"},
    )
    node_body = node_resp.json()
    node_id = node_body["id"]
    assert node_body["parent_id"] is None
    assert node_body["position"] == 0

    _request(
        "POST",
        f"/api/v1/nodes/{node_id}/bind/{document_id}",
        headers=_auth_headers("author"),
    )

    # --- 更新文档、节点与关系 ---
    doc_update = _request(
        "PUT",
        f"/api/v1/documents/{document_id}",
        headers=_auth_headers("editor"),
        json={
            "title": "Workflow Doc v2",
            "metadata": {"stage": "final"},
            "content": {"body": "final"},
        },
    ).json()
    assert doc_update["title"] == "Workflow Doc v2"
    assert doc_update["content"]["body"] == "final"

    node_update = _request(
        "PUT",
        f"/api/v1/nodes/{node_id}",
        headers=_auth_headers("editor"),
        json={"slug": "workflow-v2"},
    ).json()
    assert node_update["path"] == "workflow-v2"
    assert node_update["parent_id"] is None
    assert node_update["position"] == 0

    _request(
        "POST",
        "/api/v1/relationships",
        headers=_auth_headers("editor"),
        params={"node_id": node_id, "document_id": document_id},
    )

    # --- 删除关系、节点、文档（软删） ---
    _request(
        "DELETE",
        f"/api/v1/nodes/{node_id}/unbind/{document_id}",
        headers=_auth_headers("operator"),
    )

    _request(
        "DELETE",
        f"/api/v1/nodes/{node_id}",
        headers=_auth_headers("operator"),
    )

    _request(
        "DELETE",
        f"/api/v1/documents/{document_id}",
        headers=_auth_headers("operator"),
    )

    assert (
        requests.get(
            f"{_base_url()}/api/v1/nodes/{node_id}", headers=_auth_headers("auditor")
        ).status_code
        == 404
    )
    assert (
        requests.get(
            f"{_base_url()}/api/v1/documents/{document_id}",
            headers=_auth_headers("auditor"),
        ).status_code
        == 404
    )

    node_deleted = _request(
        "GET",
        f"/api/v1/nodes/{node_id}",
        headers=_auth_headers("auditor"),
        params={"include_deleted": "true"},
    ).json()
    assert node_deleted["deleted_at"] is not None

    doc_deleted = _request(
        "GET",
        f"/api/v1/documents/{document_id}",
        headers=_auth_headers("auditor"),
        params={"include_deleted": "true"},
    ).json()
    assert doc_deleted["deleted_at"] is not None

    # --- 使用官方 API 恢复 ---
    _request(
        "POST",
        f"/api/v1/nodes/{node_id}/restore",
        headers=_auth_headers("restorer"),
    )

    _request(
        "POST",
        f"/api/v1/documents/{document_id}/restore",
        headers=_auth_headers("restorer"),
    )

    _request(
        "POST",
        f"/api/v1/nodes/{node_id}/bind/{document_id}",
        headers=_auth_headers("restorer"),
    )

    restored_node = _request(
        "GET",
        f"/api/v1/nodes/{node_id}",
        headers=_auth_headers("auditor"),
    ).json()
    assert restored_node["parent_id"] is None
    assert restored_node["position"] == 0

    restored_doc = _request(
        "GET",
        f"/api/v1/documents/{document_id}",
        headers=_auth_headers("auditor"),
    ).json()
    assert restored_doc["content"]["body"] == "final"

    rels = _request(
        "GET",
        "/api/v1/relationships",
        headers=_auth_headers("auditor"),
        params={"node_id": node_id},
    ).json()
    assert any(rel["document_id"] == document_id for rel in rels)


def test_create_node_and_list_requests():
    slug = f"requests-root-{uuid.uuid4().hex[:8]}"
    create_resp = _request(
        "POST",
        "/api/v1/nodes",
        headers=_auth_headers("creator"),
        json={"name": f"Requests Root {slug}", "slug": slug},
    ).json()
    node_id = create_resp["id"]
    assert create_resp["parent_id"] is None

    nodes_page = _request(
        "GET",
        "/api/v1/nodes",
        headers=_auth_headers("auditor"),
        params={"page": 1, "size": 50},
    ).json()
    assert any(item["slug"] == slug for item in nodes_page["items"])

    _request(
        "DELETE",
        f"/api/v1/nodes/{node_id}",
        headers=_auth_headers("cleaner"),
    )
