from fastapi.testclient import TestClient

from app.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_full_workflow_with_soft_delete_and_restore():
    client = _client()

    # --- 创建文档与节点，并建立关系 ---
    doc_resp = client.post(
        "/api/v1/documents",
        json={
            "title": "Workflow Doc",
            "metadata": {"stage": "draft"},
            "content": {"body": "initial"},
        },
        headers={"X-User-Id": "author"},
    )
    assert doc_resp.status_code == 201
    document_id = doc_resp.json()["id"]
    assert doc_resp.json()["version_number"] == 1

    node_resp = client.post(
        "/api/v1/nodes",
        json={"name": "Workflow Node", "slug": "workflow"},
        headers={"X-User-Id": "author"},
    )
    assert node_resp.status_code == 201
    node_id = node_resp.json()["id"]
    assert node_resp.json()["parent_id"] is None
    assert node_resp.json()["position"] == 0

    bind_resp = client.post(
        f"/api/v1/nodes/{node_id}/bind/{document_id}",
        headers={"X-User-Id": "author"},
    )
    assert bind_resp.status_code == 200

    # --- 更新文档、节点与关系 ---
    doc_update = client.put(
        f"/api/v1/documents/{document_id}",
        json={
            "title": "Workflow Doc v2",
            "metadata": {"stage": "final"},
            "content": {"body": "final"},
        },
        headers={"X-User-Id": "editor"},
    )
    assert doc_update.status_code == 200
    assert doc_update.json()["title"] == "Workflow Doc v2"
    assert doc_update.json()["content"]["body"] == "final"
    assert doc_update.json()["version_number"] == 2  # 版本号应已更新

    node_update = client.put(
        f"/api/v1/nodes/{node_id}",
        json={"slug": "workflow-v2"},
        headers={"X-User-Id": "editor"},
    )
    assert node_update.status_code == 200
    assert node_update.json()["path"] == "workflow-v2"
    assert node_update.json()["parent_id"] is None
    assert node_update.json()["position"] == 0

    rebind_resp = client.post(
        "/api/v1/relationships",
        params={"node_id": node_id, "document_id": document_id},
        headers={"X-User-Id": "editor"},
    )
    assert rebind_resp.status_code == 201

    # --- 删除关系、节点、文档（软删） ---
    unbind_resp = client.delete(
        f"/api/v1/nodes/{node_id}/unbind/{document_id}",
        headers={"X-User-Id": "operator"},
    )
    assert unbind_resp.status_code == 200

    delete_node = client.delete(
        f"/api/v1/nodes/{node_id}",
        headers={"X-User-Id": "operator"},
    )
    assert delete_node.status_code == 204

    delete_doc = client.delete(
        f"/api/v1/documents/{document_id}",
        headers={"X-User-Id": "operator"},
    )
    assert delete_doc.status_code == 204

    # 验证软删状态
    assert client.get(f"/api/v1/nodes/{node_id}").status_code == 404
    assert client.get(f"/api/v1/documents/{document_id}").status_code == 404

    node_deleted = client.get(f"/api/v1/nodes/{node_id}?include_deleted=true")
    assert node_deleted.status_code == 200
    assert node_deleted.json()["deleted_at"] is not None

    doc_deleted = client.get(f"/api/v1/documents/{document_id}?include_deleted=true")
    assert doc_deleted.status_code == 200
    assert doc_deleted.json()["deleted_at"] is not None

    # --- 使用官方 API 恢复 ---
    restore_node = client.post(
        f"/api/v1/nodes/{node_id}/restore",
        headers={"X-User-Id": "restorer"},
    )
    assert restore_node.status_code == 200

    restore_doc = client.post(
        f"/api/v1/documents/{document_id}/restore",
        headers={"X-User-Id": "restorer"},
    )
    assert restore_doc.status_code == 200
    assert restore_doc.json()["version_number"] >= 3

    # 重新绑定关系并验证恢复
    restore_bind = client.post(
        f"/api/v1/nodes/{node_id}/bind/{document_id}",
        headers={"X-User-Id": "restorer"},
    )
    assert restore_bind.status_code == 200

    restored_node = client.get(f"/api/v1/nodes/{node_id}")
    assert restored_node.status_code == 200
    assert restored_node.json()["parent_id"] is None
    assert restored_node.json()["position"] == 0
    restored_doc = client.get(f"/api/v1/documents/{document_id}")
    assert restored_doc.status_code == 200
    assert restored_doc.json()["content"]["body"] == "final"

    rels = client.get(f"/api/v1/relationships?node_id={node_id}").json()
    assert any(rel["document_id"] == document_id for rel in rels)


def test_query_documents_with_complex_metadata():
    client = _client()
    headers = {"X-User-Id": "author"}
    payloads = [
        {
            "title": "Complex Doc A",
            "metadata": {
                "tags": ["finance", "quarterly"],
                "attributes": {"region": "APAC", "score": 98.5},
                "flags": {"reviewed": True, "archived": False},
            },
            "content": {"summary": "Q1 report"},
        },
        {
            "title": "Complex Doc B",
            "metadata": {
                "tags": ["engineering"],
                "owner": {"name": "Alice", "id": 42},
                "notes": [
                    {"lang": "en", "text": "Ready for release"},
                    {"lang": "es", "text": "Listo para lanzamiento"},
                ],
            },
            "content": {"summary": "Release notes"},
        },
    ]

    created_ids: list[int] = []
    for payload in payloads:
        resp = client.post("/api/v1/documents", json=payload, headers=headers)
        assert resp.status_code == 201
        created_ids.append(resp.json()["id"])

    list_resp = client.get("/api/v1/documents", params={"page": 1, "size": 50})
    assert list_resp.status_code == 200
    listed = list_resp.json()["items"]
    docs_by_id = {doc["id"]: doc for doc in listed if doc["id"] in created_ids}
    assert set(created_ids).issubset(docs_by_id.keys())

    for payload, doc_id in zip(payloads, created_ids):
        doc = docs_by_id[doc_id]
        assert doc["title"] == payload["title"]
        assert doc["metadata"] == payload["metadata"]
        assert doc["content"] == payload["content"]
        assert "metadata_" not in doc
        assert doc["version_number"] >= 1


def test_document_versions_diff_and_restore():
    client = _client()
    headers = {"X-User-Id": "author"}

    create_resp = client.post(
        "/api/v1/documents",
        json={
            "title": "Versioned Doc",
            "metadata": {"stage": "draft"},
            "content": {"body": "v1"},
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    document_id = create_resp.json()["id"]

    update_resp = client.put(
        f"/api/v1/documents/{document_id}",
        json={
            "title": "Versioned Doc v2",
            "metadata": {"stage": "published", "approved": True},
            "content": {"body": "v2"},
        },
        headers={"X-User-Id": "editor"},
    )
    assert update_resp.status_code == 200

    versions_resp = client.get(f"/api/v1/documents/{document_id}/versions")
    assert versions_resp.status_code == 200
    versions = versions_resp.json()
    assert versions["total"] >= 2
    latest_version = max(item["version_number"] for item in versions["items"])
    assert latest_version >= 2

    diff_resp = client.get(
        f"/api/v1/documents/{document_id}/versions/1/diff",
        params={"include_deleted_document": False},
    )
    assert diff_resp.status_code == 200
    diff = diff_resp.json()
    assert diff["title"]["to"] == "Versioned Doc v2"
    assert diff["metadata"]["added"]["approved"] is True
    assert diff["content"]["changed"]["body"]["to"] == "v2"

    restore_resp = client.post(
        f"/api/v1/documents/{document_id}/versions/1/restore",
        headers={"X-User-Id": "restorer"},
    )
    assert restore_resp.status_code == 200
    restored_doc = restore_resp.json()
    assert restored_doc["title"] == "Versioned Doc"
    assert restored_doc["metadata"] == {"stage": "draft"}
    assert restored_doc["content"] == {"body": "v1"}
    assert restored_doc["version_number"] >= 3
