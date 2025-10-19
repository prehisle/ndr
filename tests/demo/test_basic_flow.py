from fastapi.testclient import TestClient

from app.main import create_app


def _client() -> TestClient:
    """Return a TestClient bound to a fresh app instance."""
    return TestClient(create_app())


def test_demo_create_document_node_and_relationship():
    """最小示例：依次创建文档、节点并建立关系。"""
    client = _client()

    doc_resp = client.post(
        "/api/v1/documents",
        json={"title": "Demo Doc", "metadata": {"tag": "demo"}},
        headers={"X-User-Id": "demo-user"},
    )
    assert doc_resp.status_code == 201
    doc_id = doc_resp.json()["id"]

    node_resp = client.post(
        "/api/v1/nodes",
        json={"name": "Demo Node", "slug": "demo"},
        headers={"X-User-Id": "demo-user"},
    )
    assert node_resp.status_code == 201
    node_id = node_resp.json()["id"]

    bind_resp = client.post(
        f"/api/v1/nodes/{node_id}/bind/{doc_id}",
        headers={"X-User-Id": "demo-user"},
    )
    assert bind_resp.status_code == 200


def test_demo_update_document_node_and_relationship():
    """示例：更新文档、节点与关系。"""
    client = _client()

    # 创建文档并更新标题/元数据
    doc_resp = client.post(
        "/api/v1/documents",
        json={"title": "Initial", "metadata": {"stage": "draft"}},
        headers={"X-User-Id": "author"},
    )
    doc_id = doc_resp.json()["id"]
    update_doc = client.put(
        f"/api/v1/documents/{doc_id}",
        json={"title": "Revised", "metadata": {"stage": "final"}},
        headers={"X-User-Id": "editor"},
    )
    assert update_doc.status_code == 200
    assert update_doc.json()["title"] == "Revised"

    # 创建节点并更新 slug（演示子树路径跟随变化）
    node_resp = client.post(
        "/api/v1/nodes",
        json={"name": "Section", "slug": "section"},
        headers={"X-User-Id": "author"},
    )
    node_id = node_resp.json()["id"]
    update_node = client.put(
        f"/api/v1/nodes/{node_id}",
        json={"slug": "section-v2"},
        headers={"X-User-Id": "editor"},
    )
    assert update_node.status_code == 200
    assert update_node.json()["path"] == "section-v2"

    # 绑定关系，并以新的用户再次绑定演示“更新”场景（更新 updated_by）
    bind_resp = client.post(
        "/api/v1/relationships",
        params={"node_id": node_id, "document_id": doc_id},
        headers={"X-User-Id": "author"},
    )
    assert bind_resp.status_code == 201

    rebind_resp = client.post(
        "/api/v1/relationships",
        params={"node_id": node_id, "document_id": doc_id},
        headers={"X-User-Id": "editor"},
    )
    # 复用原记录，相当于更新关系的操作人信息
    assert rebind_resp.status_code == 201


def test_demo_delete_document_node_and_relationship():
    """示例：删除文档（软删）、删除节点与关系。"""
    client = _client()

    # 准备基础数据
    doc_resp = client.post(
        "/api/v1/documents",
        json={"title": "To Delete", "metadata": {}},
        headers={"X-User-Id": "demo"},
    )
    doc_id = doc_resp.json()["id"]

    node_resp = client.post(
        "/api/v1/nodes",
        json={"name": "To Delete", "slug": "to-delete"},
        headers={"X-User-Id": "demo"},
    )
    node_id = node_resp.json()["id"]

    client.post(
        f"/api/v1/nodes/{node_id}/bind/{doc_id}",
        headers={"X-User-Id": "demo"},
    )

    # 删除关系
    unbind_resp = client.delete(
        f"/api/v1/nodes/{node_id}/unbind/{doc_id}",
        headers={"X-User-Id": "demo"},
    )
    assert unbind_resp.status_code == 200

    # 删除节点（软删）
    delete_node = client.delete(
        f"/api/v1/nodes/{node_id}",
        headers={"X-User-Id": "demo"},
    )
    assert delete_node.status_code == 204
    assert client.get(f"/api/v1/nodes/{node_id}").status_code == 404

    # 删除文档（软删）
    delete_doc = client.delete(
        f"/api/v1/documents/{doc_id}",
        headers={"X-User-Id": "demo"},
    )
    assert delete_doc.status_code == 204
    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 404
