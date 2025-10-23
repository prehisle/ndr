from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.infra.db.models import Document
from app.infra.db.session import get_session_factory
from app.main import create_app


def test_document_crud_and_soft_delete():
    app = create_app()
    client = TestClient(app)

    # Create
    payload = {
        "title": "Spec A",
        "metadata": {"type": "spec"},
        "content": {"body": "spec"},
    }
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
    r = client.put(
        f"/api/v1/documents/{doc_id}",
        json={"title": "Spec B"},
        headers={"X-User-Id": "u2"},
    )
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

    # Restore
    restore = client.post(
        f"/api/v1/documents/{doc_id}/restore",
        headers={"X-User-Id": "u4"},
    )
    assert restore.status_code == 200
    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 200


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
    assert root["path"] == "root"
    assert root["parent_id"] is None
    assert root["position"] == 0

    # Create second root node to support later move
    r = client.post(
        "/api/v1/nodes",
        json={"name": "Other Root", "slug": "other-root"},
        headers={"X-User-Id": "u1"},
    )
    assert r.status_code == 201
    other_root = r.json()
    other_root_id = other_root["id"]
    assert other_root["position"] == 1

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
    assert child["parent_id"] == root["id"]
    assert child["position"] == 0

    # Create grandchild under child path
    r = client.post(
        "/api/v1/nodes",
        json={"name": "Grand", "slug": "grand", "parent_path": "root.child"},
        headers={"X-User-Id": "u1"},
    )
    assert r.status_code == 201
    grand = r.json()
    grand_id = grand["id"]
    assert grand["parent_id"] == child_id
    assert grand["position"] == 0

    # Update child slug -> entire subtree path updates
    r = client.put(
        f"/api/v1/nodes/{child_id}",
        json={"slug": "kid"},
        headers={"X-User-Id": "u2"},
    )
    assert r.status_code == 200
    child = r.json()
    assert child["path"] == "root.kid"
    assert child["parent_id"] == root["id"]
    assert child["position"] == 0
    r = client.get(f"/api/v1/nodes/{grand_id}")
    assert r.status_code == 200
    grand_fetched = r.json()
    assert grand_fetched["path"] == "root.kid.grand"
    assert grand_fetched["parent_id"] == child_id
    assert grand_fetched["position"] == 0

    # Move child subtree under second root
    r = client.put(
        f"/api/v1/nodes/{child_id}",
        json={"parent_path": "other-root"},
        headers={"X-User-Id": "u3"},
    )
    assert r.status_code == 200
    child = r.json()
    assert child["path"] == "other-root.kid"
    assert child["parent_id"] == other_root_id
    assert child["position"] == 0
    r = client.get(f"/api/v1/nodes/{grand_id}")
    assert r.status_code == 200
    grand_fetched = r.json()
    assert grand_fetched["path"] == "other-root.kid.grand"
    assert grand_fetched["parent_id"] == child_id
    assert grand_fetched["position"] == 0

    # List nodes (exclude deleted)
    r = client.get("/api/v1/nodes?page=1&size=10")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 2
    assert len(data["items"]) >= 2
    assert all("parent_id" in item for item in data["items"])
    assert all("position" in item for item in data["items"])

    # Children depth=1 should only include immediate children
    r = client.get(f"/api/v1/nodes/{other_root_id}/children?depth=1")
    assert r.status_code == 200
    children = r.json()
    assert [n["id"] for n in children] == [child_id]
    assert [n["parent_id"] for n in children] == [other_root_id]
    assert [n["position"] for n in children] == [0]

    # Depth=2 should include grandchildren
    r = client.get(f"/api/v1/nodes/{other_root_id}/children?depth=2")
    assert r.status_code == 200
    depth_two = r.json()
    assert [n["id"] for n in depth_two] == [child_id, grand_id]
    parent_map = {n["id"]: n["parent_id"] for n in depth_two}
    assert parent_map[child_id] == other_root_id
    assert parent_map[grand_id] == child_id

    # Add another child under other_root to exercise reorder API
    r = client.post(
        "/api/v1/nodes",
        json={"name": "Sibling", "slug": "sibling", "parent_path": "other-root"},
        headers={"X-User-Id": "u4"},
    )
    assert r.status_code == 201
    sibling = r.json()
    sibling_id = sibling["id"]
    assert sibling["parent_id"] == other_root_id
    assert sibling["position"] == 1

    reorder_payload = {"parent_id": other_root_id, "ordered_ids": [sibling_id]}
    r = client.post(
        "/api/v1/nodes/reorder",
        json=reorder_payload,
        headers={"X-User-Id": "u4"},
    )
    assert r.status_code == 200
    reordered = r.json()
    assert [node["id"] for node in reordered] == [sibling_id, child_id]
    assert [node["position"] for node in reordered] == [0, 1]

    r = client.get(f"/api/v1/nodes/{other_root_id}/children?depth=1")
    ordered_children = r.json()
    assert [n["id"] for n in ordered_children] == [sibling_id, child_id]
    assert [n["position"] for n in ordered_children] == [0, 1]

    # Reorder root nodes to move other_root before root
    r = client.post(
        "/api/v1/nodes/reorder",
        json={"parent_id": None, "ordered_ids": [other_root_id]},
        headers={"X-User-Id": "u4"},
    )
    assert r.status_code == 200
    root_order = r.json()
    assert root_order[0]["id"] == other_root_id
    assert root_order[0]["position"] == 0
    assert root_order[1]["id"] == root["id"]

    # Bind document to child
    dr = client.post(
        "/api/v1/documents",
        json={"title": "Doc", "metadata": {}, "content": {"body": "doc"}},
        headers={"X-User-Id": "u1"},
    )
    doc_id = dr.json()["id"]
    r = client.post(
        f"/api/v1/nodes/{child_id}/bind/{doc_id}", headers={"X-User-Id": "u1"}
    )
    assert r.status_code == 200

    # Subtree documents from other_root should include the bound document
    r = client.get(f"/api/v1/nodes/{other_root_id}/subtree-documents")
    assert r.status_code == 200
    subtree_docs = r.json()["items"]
    assert any(d["id"] == doc_id for d in subtree_docs)

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

    # Subtree documents after unbind should be empty
    r = client.get(f"/api/v1/nodes/{other_root_id}/subtree-documents")
    assert r.status_code == 200
    assert r.json()["items"] == []

    # Soft delete child node and restore
    delete_child = client.delete(
        f"/api/v1/nodes/{child_id}",
        headers={"X-User-Id": "u5"},
    )
    assert delete_child.status_code == 204
    assert client.get(f"/api/v1/nodes/{child_id}").status_code == 404

    restore_child = client.post(
        f"/api/v1/nodes/{child_id}/restore",
        headers={"X-User-Id": "u6"},
    )
    assert restore_child.status_code == 200
    assert client.get(f"/api/v1/nodes/{child_id}").status_code == 200


def test_list_documents_supports_metadata_and_query_filters():
    app = create_app()
    client = TestClient(app)
    headers = {"X-User-Id": "searcher"}

    docs = [
        {
            "title": "Alpha Spec",
            "metadata": {"stage": "draft", "tags": ["alpha", "beta"]},
            "content": {"body": "Alpha entry"},
        },
        {
            "title": "Beta Spec",
            "metadata": {"stage": "final", "tags": ["beta"]},
            "content": {"body": "Production ready"},
        },
        {
            "title": "Gamma Spec",
            "metadata": {"stage": "draft", "tags": []},
            "content": {"body": "Gamma notes"},
        },
    ]
    created_ids: list[int] = []
    for payload in docs:
        resp = client.post("/api/v1/documents", json=payload, headers=headers)
        assert resp.status_code == 201
        created_ids.append(resp.json()["id"])

    # Filter by metadata equality
    stage_resp = client.get("/api/v1/documents", params={"metadata.stage": "draft"})
    assert stage_resp.status_code == 200
    stage_ids = {doc["id"] for doc in stage_resp.json()["items"]}
    assert stage_ids == {created_ids[0], created_ids[2]}

    # Filter by metadata tags from array
    tag_resp = client.get("/api/v1/documents", params={"metadata.tags": "alpha"})
    assert tag_resp.status_code == 200
    tag_items = tag_resp.json()["items"]
    assert {item["id"] for item in tag_items} == {created_ids[0]}

    # Multiple values for same key acts as OR
    stage_multi = client.get(
        "/api/v1/documents",
        params=[("metadata.stage", "draft"), ("metadata.stage", "final")],
    )
    assert stage_multi.status_code == 200
    multi_ids = {doc["id"] for doc in stage_multi.json()["items"]}
    assert multi_ids == set(created_ids)

    # Fuzzy search across title/content
    search_resp = client.get("/api/v1/documents", params={"query": "Alpha"})
    assert search_resp.status_code == 200
    search_ids = {doc["id"] for doc in search_resp.json()["items"]}
    assert created_ids[0] in search_ids
    assert created_ids[1] not in search_ids

    # Combined metadata + search narrows results
    combo_resp = client.get(
        "/api/v1/documents",
        params={"metadata.stage": "draft", "query": "Gamma"},
    )
    assert combo_resp.status_code == 200
    combo_items = combo_resp.json()["items"]
    assert {doc["id"] for doc in combo_items} == {created_ids[2]}


def test_subtree_documents_supports_filters():
    app = create_app()
    client = TestClient(app)
    headers = {"X-User-Id": "tree"}

    node = client.post(
        "/api/v1/nodes",
        json={"name": "Root", "slug": "root"},
        headers=headers,
    ).json()
    child = client.post(
        "/api/v1/nodes",
        json={"name": "Child", "slug": "child", "parent_path": "root"},
        headers=headers,
    ).json()

    doc_alpha = client.post(
        "/api/v1/documents",
        json={
            "title": "Alpha Doc",
            "metadata": {"stage": "draft", "tags": ["alpha"]},
            "content": {"body": "Alpha section"},
        },
        headers=headers,
    ).json()
    doc_beta = client.post(
        "/api/v1/documents",
        json={
            "title": "Beta Doc",
            "metadata": {"stage": "final", "tags": ["beta"]},
            "content": {"body": "Beta section"},
        },
        headers=headers,
    ).json()

    assert (
        client.post(
            f"/api/v1/nodes/{child['id']}/bind/{doc_alpha['id']}",
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/nodes/{child['id']}/bind/{doc_beta['id']}",
            headers=headers,
        ).status_code
        == 200
    )

    tag_resp = client.get(
        f"/api/v1/nodes/{node['id']}/subtree-documents",
        params={"metadata.tags": "alpha"},
    )
    assert tag_resp.status_code == 200
    assert {doc["id"] for doc in tag_resp.json()["items"]} == {doc_alpha["id"]}

    search_resp = client.get(
        f"/api/v1/nodes/{node['id']}/subtree-documents",
        params={"query": "Beta"},
    )
    assert search_resp.status_code == 200
    assert {doc["id"] for doc in search_resp.json()["items"]} == {doc_beta["id"]}

    combo_resp = client.get(
        f"/api/v1/nodes/{node['id']}/subtree-documents",
        params={"metadata.stage": "draft", "query": "Alpha"},
    )
    assert combo_resp.status_code == 200
    assert {doc["id"] for doc in combo_resp.json()["items"]} == {doc_alpha["id"]}


def test_children_type_filter_and_traversal():
    app = create_app()
    client = TestClient(app)
    headers = {"X-User-Id": "u-type"}

    # 创建根节点
    root = client.post(
        "/api/v1/nodes",
        json={"name": "RootT", "slug": "root-t"},
        headers=headers,
    ).json()

    # 在根下创建两个子节点，类型不同
    child_a = client.post(
        "/api/v1/nodes",
        json={
            "name": "A",
            "slug": "a",
            "parent_path": "root-t",
            "type": "document",
        },
        headers=headers,
    ).json()
    child_b = client.post(
        "/api/v1/nodes",
        json={
            "name": "B",
            "slug": "b",
            "parent_path": "root-t",
            "type": "folder",
        },
        headers=headers,
    ).json()

    # 在不匹配类型的子节点 A 下创建一个匹配类型的孙节点 AA
    grand_aa = client.post(
        "/api/v1/nodes",
        json={
            "name": "AA",
            "slug": "aa",
            "parent_path": "root-t.a",
            "type": "folder",
        },
        headers=headers,
    ).json()

    # 过滤 type=folder，depth=2，应包含 child_b 与 grand_aa，且遍历跨越不匹配的 A
    resp = client.get(
        f"/api/v1/nodes/{root['id']}/children",
        params={"depth": 2, "type": "folder"},
    )
    assert resp.status_code == 200
    items = resp.json()
    ids = [n["id"] for n in items]
    assert ids == [child_b["id"], grand_aa["id"]]
    # 验证父子关系
    parent_map = {n["id"]: n["parent_id"] for n in items}
    assert parent_map[child_b["id"]] == root["id"]
    assert parent_map[grand_aa["id"]] == child_a["id"]


def test_subtree_documents_include_descendants_toggle():
    app = create_app()
    client = TestClient(app)
    headers = {"X-User-Id": "toggle"}

    root = client.post(
        "/api/v1/nodes",
        json={"name": "Root", "slug": "root"},
        headers=headers,
    ).json()
    child = client.post(
        "/api/v1/nodes",
        json={"name": "Child", "slug": "child", "parent_path": "root"},
        headers=headers,
    ).json()

    root_doc = client.post(
        "/api/v1/documents",
        json={"title": "Root Doc", "metadata": {}, "content": {}},
        headers=headers,
    ).json()
    child_doc = client.post(
        "/api/v1/documents",
        json={"title": "Child Doc", "metadata": {}, "content": {}},
        headers=headers,
    ).json()

    assert (
        client.post(
            f"/api/v1/nodes/{root['id']}/bind/{root_doc['id']}",
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/nodes/{child['id']}/bind/{child_doc['id']}",
            headers=headers,
        ).status_code
        == 200
    )

    all_docs = client.get(
        f"/api/v1/nodes/{root['id']}/subtree-documents",
    )
    assert all_docs.status_code == 200
    assert {doc["id"] for doc in all_docs.json()["items"]} == {
        root_doc["id"],
        child_doc["id"],
    }

    direct_docs = client.get(
        f"/api/v1/nodes/{root['id']}/subtree-documents",
        params={"include_descendants": "false"},
    )
    assert direct_docs.status_code == 200
    assert {doc["id"] for doc in direct_docs.json()["items"]} == {root_doc["id"]}


def test_create_node_with_missing_parent_returns_404():
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/v1/nodes",
        json={"name": "Orphan", "slug": "orphan", "parent_path": "missing"},
        headers={"X-User-Id": "tester"},
    )
    assert response.status_code == 404


def test_permanent_delete_requires_admin_key():
    app = create_app()
    client = TestClient(app)

    doc_resp = client.post(
        "/api/v1/documents",
        json={"title": "Doc", "metadata": {}, "content": {}},
        headers={"X-User-Id": "author"},
    )
    assert doc_resp.status_code == 201
    document_id = doc_resp.json()["id"]

    node_resp = client.post(
        "/api/v1/nodes",
        json={"name": "Root", "slug": "root"},
        headers={"X-User-Id": "author"},
    )
    assert node_resp.status_code == 201
    node_id = node_resp.json()["id"]

    soft_delete_doc = client.delete(
        f"/api/v1/documents/{document_id}",
        headers={"X-User-Id": "deleter"},
    )
    assert soft_delete_doc.status_code == 204

    soft_delete_node = client.delete(
        f"/api/v1/nodes/{node_id}",
        headers={"X-User-Id": "deleter"},
    )
    assert soft_delete_node.status_code == 204

    # Missing admin key -> forbidden
    assert (
        client.delete(
            f"/api/v1/documents/{document_id}/purge",
            headers={"X-User-Id": "admin"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/nodes/{node_id}/purge",
            headers={"X-User-Id": "admin"},
        ).status_code
        == 403
    )

    admin_headers = {"X-User-Id": "admin", "X-Admin-Key": "admin-secret"}
    assert (
        client.delete(
            f"/api/v1/documents/{document_id}/purge", headers=admin_headers
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/nodes/{node_id}/purge", headers=admin_headers
        ).status_code
        == 204
    )

    assert (
        client.get(
            f"/api/v1/documents/{document_id}?include_deleted=true",
            headers={"X-User-Id": "auditor"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/nodes/{node_id}?include_deleted=true",
            headers={"X-User-Id": "auditor"},
        ).status_code
        == 404
    )


def test_document_versions_api():
    app = create_app()
    client = TestClient(app)

    create = client.post(
        "/api/v1/documents",
        json={
            "title": "Versioned",
            "metadata": {"stage": "draft"},
            "content": {"body": "v1"},
        },
        headers={"X-User-Id": "author"},
    )
    assert create.status_code == 201
    doc_id = create.json()["id"]

    update = client.put(
        f"/api/v1/documents/{doc_id}",
        json={
            "title": "Versioned v2",
            "metadata": {"stage": "published", "approved": True},
            "content": {"body": "v2"},
        },
        headers={"X-User-Id": "editor"},
    )
    assert update.status_code == 200

    versions = client.get(f"/api/v1/documents/{doc_id}/versions")
    assert versions.status_code == 200
    data = versions.json()
    assert data["total"] >= 2
    numbers = {item["version_number"] for item in data["items"]}
    assert numbers == {1, 2}

    version_one = client.get(
        f"/api/v1/documents/{doc_id}/versions/1",
        params={"include_deleted_document": False},
    )
    assert version_one.status_code == 200
    assert version_one.json()["title"] == "Versioned"

    diff = client.get(
        f"/api/v1/documents/{doc_id}/versions/1/diff",
        params={"include_deleted_document": False},
    )
    assert diff.status_code == 200
    diff_body = diff.json()
    assert diff_body["metadata"]["added"]["approved"] is True

    restore = client.post(
        f"/api/v1/documents/{doc_id}/versions/1/restore",
        headers={"X-User-Id": "restorer"},
    )
    assert restore.status_code == 200
    assert restore.json()["title"] == "Versioned"


def test_document_idempotency_key_reuses_response():
    app = create_app()
    client = TestClient(app)

    headers = {"X-User-Id": "u1", "Idempotency-Key": "doc-create-1"}
    payload = {
        "title": "Spec C",
        "metadata": {"type": "spec"},
        "content": {"body": "spec"},
    }
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
        json={
            "title": "Spec D",
            "metadata": {"type": "spec"},
            "content": {"body": "spec"},
        },
        headers=headers,
    )
    assert r3.status_code == 409

    session_factory = get_session_factory()
    with session_factory() as session:
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

    # Moving root under its descendant should be rejected
    root_id = r_root.json()["id"]
    r_invalid_move = client.put(
        f"/api/v1/nodes/{root_id}",
        json={"parent_path": "root.child"},
        headers=headers,
    )
    assert r_invalid_move.status_code == 400

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
    doc_resp = client.post(
        "/api/v1/documents", json={"title": "Doc", "metadata": {}}, headers=headers
    )
    doc_id = doc_resp.json()["id"]
    bind_resp = client.post(f"/api/v1/nodes/{child_id}/bind/{doc_id}", headers=headers)
    assert bind_resp.status_code == 200

    unbind_resp = client.delete(
        f"/api/v1/nodes/{child_id}/unbind/{doc_id}", headers=headers
    )
    assert unbind_resp.status_code == 200

    # Rebind should reopen existing relation (not create duplicate)
    rebind_resp = client.post(
        f"/api/v1/nodes/{child_id}/bind/{doc_id}", headers=headers
    )
    assert rebind_resp.status_code == 200
    rels = client.get(f"/api/v1/relationships?node_id={child_id}").json()
    assert len(rels) == 1


def test_subtree_documents_type_filter():
    app = create_app()
    client = TestClient(app)
    headers = {"X-User-Id": "type-docs"}

    root = client.post(
        "/api/v1/nodes",
        json={"name": "TRoot", "slug": "t-root"},
        headers=headers,
    ).json()
    child = client.post(
        "/api/v1/nodes",
        json={"name": "TChild", "slug": "t-child", "parent_path": "t-root"},
        headers=headers,
    ).json()

    root_doc = client.post(
        "/api/v1/documents",
        json={"title": "Root Spec", "type": "spec", "metadata": {}, "content": {}},
        headers=headers,
    ).json()
    child_doc1 = client.post(
        "/api/v1/documents",
        json={"title": "Child Note", "type": "note", "metadata": {}, "content": {}},
        headers=headers,
    ).json()
    child_doc2 = client.post(
        "/api/v1/documents",
        json={"title": "Child Spec", "type": "spec", "metadata": {}, "content": {}},
        headers=headers,
    ).json()

    assert (
        client.post(
            f"/api/v1/nodes/{root['id']}/bind/{root_doc['id']}", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/nodes/{child['id']}/bind/{child_doc1['id']}", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/nodes/{child['id']}/bind/{child_doc2['id']}", headers=headers
        ).status_code
        == 200
    )

    # type=spec 默认包含后代
    r_spec = client.get(
        f"/api/v1/nodes/{root['id']}/subtree-documents",
        params={"type": "spec"},
    )
    assert r_spec.status_code == 200
    assert {d["id"] for d in r_spec.json()["items"]} == {
        root_doc["id"],
        child_doc2["id"],
    }

    # include_descendants=false 时仅返回直属文档
    r_spec_direct = client.get(
        f"/api/v1/nodes/{root['id']}/subtree-documents",
        params={"type": "spec", "include_descendants": "false"},
    )
    assert r_spec_direct.status_code == 200
    assert {d["id"] for d in r_spec_direct.json()["items"]} == {root_doc["id"]}

    # type=note 仅返回子节点的 note 文档
    r_note = client.get(
        f"/api/v1/nodes/{root['id']}/subtree-documents",
        params={"type": "note"},
    )
    assert r_note.status_code == 200
    assert {d["id"] for d in r_note.json()["items"]} == {child_doc1["id"]}


def test_subtree_documents_filters_by_id():
    app = create_app()
    client = TestClient(app)
    headers = {"X-User-Id": "filter-id"}

    # 创建节点：root 与其子节点 child
    root = client.post(
        "/api/v1/nodes",
        json={"name": "RootId", "slug": "root-id"},
        headers=headers,
    ).json()
    child = client.post(
        "/api/v1/nodes",
        json={"name": "ChildId", "slug": "child-id", "parent_path": "root-id"},
        headers=headers,
    ).json()

    # 创建 4 个文档，其中 doc4 不绑定到任何节点
    d1 = client.post(
        "/api/v1/documents",
        json={"title": "Doc1", "metadata": {}, "content": {}},
        headers=headers,
    ).json()
    d2 = client.post(
        "/api/v1/documents",
        json={"title": "Doc2", "metadata": {}, "content": {}},
        headers=headers,
    ).json()
    d3 = client.post(
        "/api/v1/documents",
        json={"title": "Doc3", "metadata": {}, "content": {}},
        headers=headers,
    ).json()
    d4 = client.post(
        "/api/v1/documents",
        json={"title": "Doc4", "metadata": {}, "content": {}},
        headers=headers,
    ).json()

    # 绑定：d1 到 root；d2、d3 到 child；d4 不绑定
    assert (
        client.post(
            f"/api/v1/nodes/{root['id']}/bind/{d1['id']}", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/nodes/{child['id']}/bind/{d2['id']}", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/nodes/{child['id']}/bind/{d3['id']}", headers=headers
        ).status_code
        == 200
    )

    # 1) include_descendants=True（默认）：按 id 过滤，返回 d1 与 d3；包含一个不存在的ID不影响结果
    resp = client.get(
        f"/api/v1/nodes/{root['id']}/subtree-documents",
        params=[("id", d1["id"]), ("id", d3["id"]), ("id", 999999)],
    )
    assert resp.status_code == 200
    ids = {doc["id"] for doc in resp.json()["items"]}
    assert ids == {d1["id"], d3["id"]}

    # 2) include_descendants=False：仅返回根节点绑定的文档（d1）
    resp2 = client.get(
        f"/api/v1/nodes/{root['id']}/subtree-documents",
        params=[("id", d1["id"]), ("id", d3["id"]), ("include_descendants", False)],
    )
    assert resp2.status_code == 200
    ids2 = {doc["id"] for doc in resp2.json()["items"]}
    assert ids2 == {d1["id"]}

    # 3) 传入未绑定到子树的文档ID（d4），应返回空列表
    resp3 = client.get(
        f"/api/v1/nodes/{root['id']}/subtree-documents",
        params=[("id", d4["id"])],
    )
    assert resp3.status_code == 200
    assert resp3.json()["items"] == []

    # 混合一个不存在的 id 也不影响返回现有匹配项
    resp2 = client.get(
        "/api/v1/documents",
        params=[("id", d2["id"]), ("id", 999999)],
    )
    assert resp2.status_code == 200
    ids2 = {item["id"] for item in resp2.json()["items"]}
    assert ids2 == {d2["id"]}


def test_subtree_documents_pagination():
    app = create_app()
    client = TestClient(app)
    headers = {"X-User-Id": "paginate"}

    root = client.post(
        "/api/v1/nodes",
        json={"name": "RootPag", "slug": "root-pag"},
        headers=headers,
    ).json()
    child = client.post(
        "/api/v1/nodes",
        json={"name": "ChildPag", "slug": "child-pag", "parent_path": "root-pag"},
        headers=headers,
    ).json()

    docs = []
    for i in range(5):
        resp = client.post(
            "/api/v1/documents",
            json={"title": f"Doc{i+1}", "metadata": {}, "content": {}},
            headers=headers,
        )
        assert resp.status_code == 201
        docs.append(resp.json())

    assert (
        client.post(
            f"/api/v1/nodes/{root['id']}/bind/{docs[0]['id']}",
            headers=headers,
        ).status_code
        == 200
    )
    for d in docs[1:]:
        assert (
            client.post(
                f"/api/v1/nodes/{child['id']}/bind/{d['id']}",
                headers=headers,
            ).status_code
            == 200
        )

    r1 = client.get(
        f"/api/v1/nodes/{root['id']}/subtree-documents",
        params={"page": 1, "size": 3},
    )
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["page"] == 1 and body1["size"] == 3 and body1["total"] == 5
    ids1 = [d["id"] for d in body1["items"]]
    assert len(ids1) == 3

    r2 = client.get(
        f"/api/v1/nodes/{root['id']}/subtree-documents",
        params={"page": 2, "size": 3},
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["page"] == 2 and body2["size"] == 3 and body2["total"] == 5
    ids2 = [d["id"] for d in body2["items"]]
    assert len(ids2) == 2

    assert set(ids1) | set(ids2) == {d["id"] for d in docs}

    r3 = client.get(
        f"/api/v1/nodes/{root['id']}/subtree-documents",
        params={"include_descendants": "false", "page": 1, "size": 10},
    )
    assert r3.status_code == 200
    body3 = r3.json()
    assert body3["total"] == 1
    assert {d["id"] for d in body3["items"]} == {docs[0]["id"]}
