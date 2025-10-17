from fastapi.testclient import TestClient
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