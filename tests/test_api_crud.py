from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.main import create_app
from app.infra.db.session import SessionLocal
from app.infra.db.models import Document, Node, NodeDocument


def test_document_crud_and_soft_delete():
    app = create_app()
    client = TestClient(app)

    # Create
    payload = {"title": "Spec A", "metadata": {"type": "spec"}}
    r = client.post("/api/v1/documents", json=payload, headers={"X-User-Id": "u1"})
    assert r.status_code == 201
    doc = r.json()
    doc_id = doc["id"]
    assert doc["created_by"] == "u1"
    assert doc["metadata"] == {"type": "spec"}

    # Get
    r = client.get(f"/api/v1/documents/{doc_id}")
    assert r.status_code == 200

    # Update
    r = client.put(f"/api/v1/documents/{doc_id}", json={"title": "Spec B"}, headers={"X-User-Id": "u2"})
    assert r.status_code == 200
    assert r.json()["title"] == "Spec B"
    assert r.json()["updated_by"] == "u2"

    # Soft delete
    r = client.delete(f"/api/v1/documents/{doc_id}", headers={"X-User-Id": "u3"})
    assert r.status_code == 204

    # Get without include_deleted -> 404
    r = client.get(f"/api/v1/documents/{doc_id}")
    assert r.status_code == 404

    # Get with include_deleted -> 200
    r = client.get(f"/api/v1/documents/{doc_id}?include_deleted=true")
    assert r.status_code == 200


def test_node_crud_and_children_and_relationships():
    app = create_app()
    client = TestClient(app)

    # Create root node
    r = client.post(
        "/api/v1/nodes",
        json={"name": "Root", "slug": "root"},
        headers={"X-User-Id": "u1"},
    )
    assert r.status_code == 201
    root = r.json()
    root_id = root["id"]
    assert root["path"] == "root"

    # Create child under root
    r = client.post(
        "/api/v1/nodes",
        json={"name": "Child", "slug": "child", "parent_path": "root"},
        headers={"X-User-Id": "u1"},
    )
    assert r.status_code == 201
    child = r.json()
    child_id = child["id"]
    assert child["path"] == "root.child"

    # Update child slug -> path changes last segment
    r = client.put(
        f"/api/v1/nodes/{child_id}",
        json={"slug": "kid"},
        headers={"X-User-Id": "u2"},
    )
    assert r.status_code == 200
    assert r.json()["path"] == "root.kid"

    # List nodes (exclude deleted)
    r = client.get("/api/v1/nodes?page=1&size=10")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 2
    assert len(data["items"]) >= 2

    # Children depth=1 should only include immediate children
    r = client.get(f"/api/v1/nodes/{root_id}/children?depth=1")
    assert r.status_code == 200
    children = r.json()
    assert any(n["id"] == child_id for n in children)

    # Bind document to child
    dr = client.post("/api/v1/documents", json={"title": "Doc", "metadata": {}}, headers={"X-User-Id": "u1"})
    doc_id = dr.json()["id"]
    r = client.post(f"/api/v1/nodes/{child_id}/bind/{doc_id}", headers={"X-User-Id": "u1"})
    assert r.status_code == 200

    # List relationships by node
    r = client.get(f"/api/v1/relationships?node_id={child_id}")
    assert r.status_code == 200
    rels = r.json()
    assert any(rel["document_id"] == doc_id for rel in rels)

    # Unbind
    r = client.delete(f"/api/v1/nodes/{child_id}/unbind/{doc_id}")
    assert r.status_code == 200

    # List relationships after unbind -> empty
    r = client.get(f"/api/v1/relationships?node_id={child_id}")
    assert r.status_code == 200
    assert r.json() == []


def test_document_idempotency_key_reuses_response():
    app = create_app()
    client = TestClient(app)

    headers = {"X-User-Id": "u1", "Idempotency-Key": "doc-create-1"}
    payload = {"title": "Spec C", "metadata": {"type": "spec"}}
    r1 = client.post("/api/v1/documents", json=payload, headers=headers)
    assert r1.status_code == 201
    created = r1.json()

    # 重新提交相同请求，应复用原响应，不重复创建
    r2 = client.post("/api/v1/documents", json=payload, headers=headers)
    assert r2.status_code == 201
    assert r2.json() == created

    # 同一 Key 但不同内容 -> 409 冲突
    r3 = client.post(
        "/api/v1/documents",
        json={"title": "Spec D", "metadata": {"type": "spec"}},
        headers=headers,
    )
    assert r3.status_code == 409

    with SessionLocal() as session:
        total = session.scalar(select(func.count()).select_from(Document))
        assert total == 1


def test_node_path_and_sibling_name_uniqueness():
    app = create_app()
    client = TestClient(app)

    headers = {"X-User-Id": "u1"}

    # Create root node
    r_root = client.post(
        "/api/v1/nodes",
        json={"name": "Root", "slug": "root"},
        headers=headers,
    )
    assert r_root.status_code == 201

    # Duplicate path (same slug under root) -> 409
    r_dup_path = client.post(
        "/api/v1/nodes",
        json={"name": "Another Root", "slug": "root"},
        headers=headers,
    )
    assert r_dup_path.status_code == 409

    # Create child under root
    r_child = client.post(
        "/api/v1/nodes",
        json={"name": "Child", "slug": "child", "parent_path": "root"},
        headers=headers,
    )
    assert r_child.status_code == 201

    # Same parent, same name -> 409 even with different slug
    r_dup_name = client.post(
        "/api/v1/nodes",
        json={"name": "Child", "slug": "child-2", "parent_path": "root"},
        headers=headers,
    )
    assert r_dup_name.status_code == 409

    # Same name under different parent should succeed
    r_other_root = client.post(
        "/api/v1/nodes",
        json={"name": "Child", "slug": "other-root"},
        headers=headers,
    )
    assert r_other_root.status_code == 201

    # Soft-delete relationship and rebind reuse existing
    child_id = r_child.json()["id"]
    doc_resp = client.post("/api/v1/documents", json={"title": "Doc", "metadata": {}}, headers=headers)
    doc_id = doc_resp.json()["id"]
    bind_resp = client.post(f"/api/v1/nodes/{child_id}/bind/{doc_id}", headers=headers)
    assert bind_resp.status_code == 200

    unbind_resp = client.delete(f"/api/v1/nodes/{child_id}/unbind/{doc_id}", headers=headers)
    assert unbind_resp.status_code == 200

    # Rebind should reopen existing relation (not create duplicate)
    rebind_resp = client.post(f"/api/v1/nodes/{child_id}/bind/{doc_id}", headers=headers)
    assert rebind_resp.status_code == 200
    rels = client.get(f"/api/v1/relationships?node_id={child_id}").json()
    assert len(rels) == 1
