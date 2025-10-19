from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import update

from app.infra.db.models import Document, Node, NodeDocument
from app.infra.db.session import get_session_factory
from app.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_full_workflow_with_soft_delete_and_restore():
    client = _client()

    # --- 创建文档与节点，并建立关系 ---
    doc_resp = client.post(
        "/api/v1/documents",
        json={"title": "Workflow Doc", "metadata": {"stage": "draft"}},
        headers={"X-User-Id": "author"},
    )
    assert doc_resp.status_code == 201
    document_id = doc_resp.json()["id"]

    node_resp = client.post(
        "/api/v1/nodes",
        json={"name": "Workflow Node", "slug": "workflow"},
        headers={"X-User-Id": "author"},
    )
    assert node_resp.status_code == 201
    node_id = node_resp.json()["id"]

    bind_resp = client.post(
        f"/api/v1/nodes/{node_id}/bind/{document_id}",
        headers={"X-User-Id": "author"},
    )
    assert bind_resp.status_code == 200

    # --- 更新文档、节点与关系 ---
    doc_update = client.put(
        f"/api/v1/documents/{document_id}",
        json={"title": "Workflow Doc v2", "metadata": {"stage": "final"}},
        headers={"X-User-Id": "editor"},
    )
    assert doc_update.status_code == 200
    assert doc_update.json()["title"] == "Workflow Doc v2"

    node_update = client.put(
        f"/api/v1/nodes/{node_id}",
        json={"slug": "workflow-v2"},
        headers={"X-User-Id": "editor"},
    )
    assert node_update.status_code == 200
    assert node_update.json()["path"] == "workflow-v2"

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

    node_deleted = client.get(
        f"/api/v1/nodes/{node_id}?include_deleted=true"
    )
    assert node_deleted.status_code == 200
    assert node_deleted.json()["deleted_at"] is not None

    doc_deleted = client.get(
        f"/api/v1/documents/{document_id}?include_deleted=true"
    )
    assert doc_deleted.status_code == 200
    assert doc_deleted.json()["deleted_at"] is not None

    # --- 恢复软删（示例：直接通过数据库更新 deleted_at 为 NULL） ---
    session_factory = get_session_factory()
    with session_factory() as session:
        now = datetime.now(timezone.utc)
        session.execute(
            update(Node)
            .where(Node.id == node_id)
            .values(deleted_at=None, updated_at=now, updated_by="restorer")
        )
        session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(deleted_at=None, updated_at=now, updated_by="restorer")
        )
        session.execute(
            update(NodeDocument)
            .where(
                NodeDocument.node_id == node_id,
                NodeDocument.document_id == document_id,
            )
            .values(deleted_at=None, updated_at=now, updated_by="restorer")
        )
        session.commit()

    # 重新绑定关系并验证恢复
    restore_bind = client.post(
        f"/api/v1/nodes/{node_id}/bind/{document_id}",
        headers={"X-User-Id": "restorer"},
    )
    assert restore_bind.status_code == 200

    restored_node = client.get(f"/api/v1/nodes/{node_id}")
    assert restored_node.status_code == 200
    restored_doc = client.get(f"/api/v1/documents/{document_id}")
    assert restored_doc.status_code == 200

    rels = client.get(f"/api/v1/relationships?node_id={node_id}").json()
    assert any(rel["document_id"] == document_id for rel in rels)
