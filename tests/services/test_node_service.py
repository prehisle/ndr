from __future__ import annotations

import pytest

from app.app.services import (
    DocumentCreateData,
    DocumentService,
    InvalidNodeOperationError,
    MissingUserError,
    NodeConflictError,
    NodeCreateData,
    NodeNotFoundError,
    NodeReorderData,
    NodeService,
    NodeUpdateData,
    ParentNodeNotFoundError,
    RelationshipService,
)
from app.infra.db.session import get_session_factory


@pytest.fixture()
def session():
    session_factory = get_session_factory()
    with session_factory() as session:
        yield session
        session.rollback()


def test_update_node_propagates_path_changes_to_descendants(session):
    service = NodeService(session)

    root = service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="u1"
    )
    assert root.parent_id is None
    assert root.position == 0
    other_root = service.create_node(
        NodeCreateData(name="Other", slug="other", parent_path=None), user_id="u1"
    )
    assert other_root.parent_id is None
    assert other_root.position == 1
    child = service.create_node(
        NodeCreateData(name="Child", slug="child", parent_path=root.path),
        user_id="u1",
    )
    assert child.parent_id == root.id
    assert child.position == 0
    grand = service.create_node(
        NodeCreateData(name="Grand", slug="grand", parent_path=child.path),
        user_id="u1",
    )
    assert grand.parent_id == child.id
    assert grand.position == 0

    updated = service.update_node(child.id, NodeUpdateData(slug="kid"), user_id="u2")
    assert updated.path == "root.kid"
    refreshed_grand = service.get_node(grand.id)
    assert refreshed_grand.path == "root.kid.grand"
    assert refreshed_grand.parent_id == child.id

    moved = service.update_node(
        child.id,
        NodeUpdateData(parent_path=other_root.path, parent_path_set=True),
        user_id="u3",
    )
    assert moved.path == "other.kid"
    assert moved.parent_id == other_root.id
    assert moved.position == 0
    moved_grand = service.get_node(grand.id)
    assert moved_grand.path == "other.kid.grand"
    assert moved_grand.parent_id == child.id

    depth_one = service.list_children(other_root.id, depth=1)
    assert [node.id for node in depth_one] == [child.id]
    assert [node.position for node in depth_one] == [0]

    depth_two = service.list_children(other_root.id, depth=2)
    assert [node.id for node in depth_two] == [child.id, grand.id]
    parent_map = {node.id: node.parent_id for node in depth_two}
    assert parent_map[child.id] == other_root.id
    assert parent_map[grand.id] == child.id


def test_create_node_enforces_parent_name_and_path_uniqueness(session):
    service = NodeService(session)
    root = service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="u1"
    )
    service.create_node(
        NodeCreateData(name="Child", slug="child", parent_path=root.path), user_id="u1"
    )

    with pytest.raises(NodeConflictError):
        service.create_node(
            NodeCreateData(name="DupChild", slug="child", parent_path=root.path),
            user_id="u1",
        )

    service.create_node(
        NodeCreateData(name="Child", slug="sibling", parent_path=None), user_id="u1"
    )


def test_reorder_children_updates_positions(session):
    service = NodeService(session)

    root = service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="owner"
    )
    child_a = service.create_node(
        NodeCreateData(name="A", slug="a", parent_path=root.path), user_id="owner"
    )
    child_b = service.create_node(
        NodeCreateData(name="B", slug="b", parent_path=root.path), user_id="owner"
    )
    child_c = service.create_node(
        NodeCreateData(name="C", slug="c", parent_path=root.path), user_id="owner"
    )

    reordered = service.reorder_children(
        NodeReorderData(parent_id=root.id, ordered_ids=(child_c.id, child_a.id)),
        user_id="operator",
    )
    assert [node.id for node in reordered] == [child_c.id, child_a.id, child_b.id]
    assert [node.position for node in reordered] == [0, 1, 2]

    children = service.list_children(root.id, depth=1)
    assert [node.id for node in children] == [child_c.id, child_a.id, child_b.id]
    assert [node.position for node in children] == [0, 1, 2]


def test_reorder_root_nodes(session):
    service = NodeService(session)

    root_a = service.create_node(
        NodeCreateData(name="RootA", slug="root-a", parent_path=None), user_id="u1"
    )
    root_b = service.create_node(
        NodeCreateData(name="RootB", slug="root-b", parent_path=None), user_id="u1"
    )
    root_c = service.create_node(
        NodeCreateData(name="RootC", slug="root-c", parent_path=None), user_id="u1"
    )

    reordered = service.reorder_children(
        NodeReorderData(parent_id=None, ordered_ids=(root_c.id, root_a.id)),
        user_id="u2",
    )
    assert [node.id for node in reordered][:3] == [root_c.id, root_a.id, root_b.id]
    assert [node.position for node in reordered][:3] == [0, 1, 2]


def test_purge_node_requires_soft_delete(session):
    node_service = NodeService(session)
    document_service = DocumentService(session)
    relationship_service = RelationshipService(session)

    root = node_service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="owner"
    )
    child = node_service.create_node(
        NodeCreateData(name="Child", slug="child", parent_path=root.path),
        user_id="owner",
    )
    document = document_service.create_document(
        DocumentCreateData(title="Doc", metadata={}, content={}),
        user_id="owner",
    )
    relationship_service.bind(child.id, document.id, user_id="owner")

    with pytest.raises(InvalidNodeOperationError):
        node_service.purge_node(child.id, user_id="admin")

    node_service.soft_delete_node(child.id, user_id="deleter")
    node_service.purge_node(child.id, user_id="admin")

    with pytest.raises(NodeNotFoundError):
        node_service.get_node(child.id, include_deleted=True)
    assert relationship_service.list(node_id=child.id) == []


def test_create_node_requires_existing_parent_when_specified(session):
    service = NodeService(session)
    with pytest.raises(ParentNodeNotFoundError):
        service.create_node(
            NodeCreateData(name="Orphan", slug="orphan", parent_path="missing"),
            user_id="u1",
        )


def test_soft_delete_node_requires_active_record(session):
    service = NodeService(session)
    node = service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="u1"
    )

    service.soft_delete_node(node.id, user_id="u2")

    with pytest.raises(NodeNotFoundError):
        service.soft_delete_node(node.id, user_id="u3")


def test_get_subtree_documents_respects_deleted_flags(session):
    node_service = NodeService(session)
    document_service = DocumentService(session)
    relationship_service = RelationshipService(session)

    root = node_service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="author"
    )
    child = node_service.create_node(
        NodeCreateData(name="Child", slug="child", parent_path=root.path),
        user_id="author",
    )

    doc_root = document_service.create_document(
        DocumentCreateData(title="Root Doc", metadata={"type": "root"}),
        user_id="author",
    )
    doc_child = document_service.create_document(
        DocumentCreateData(title="Child Doc"), user_id="author"
    )

    relationship_service.bind(root.id, doc_root.id, user_id="author")
    relationship_service.bind(child.id, doc_child.id, user_id="author")

    docs = node_service.get_subtree_documents(root.id)
    assert {d.id for d in docs} == {doc_root.id, doc_child.id}

    document_service.soft_delete_document(doc_child.id, user_id="author")

    docs_default = node_service.get_subtree_documents(root.id)
    assert {d.id for d in docs_default} == {doc_root.id}

    docs_with_deleted_docs = node_service.get_subtree_documents(
        root.id, include_deleted_documents=True
    )
    assert {d.id for d in docs_with_deleted_docs} == {doc_root.id, doc_child.id}

    node_service.soft_delete_node(child.id, user_id="author")

    docs_excluding_deleted_nodes = node_service.get_subtree_documents(root.id)
    assert {d.id for d in docs_excluding_deleted_nodes} == {doc_root.id}

    docs_including_deleted_nodes = node_service.get_subtree_documents(
        root.id,
        include_deleted_nodes=True,
        include_deleted_documents=True,
    )
    assert {d.id for d in docs_including_deleted_nodes} == {doc_root.id, doc_child.id}


def test_node_service_requires_user_context(session):
    service = NodeService(session)

    with pytest.raises(MissingUserError):
        service.create_node(
            NodeCreateData(name="Root", slug="root", parent_path=None),
            user_id="",
        )

    root = service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="u1"
    )

    with pytest.raises(MissingUserError):
        service.update_node(
            root.id,
            NodeUpdateData(name="Root2"),
            user_id="",
        )


def test_node_service_restore(session):
    service = NodeService(session)
    node = service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None),
        user_id="author",
    )

    service.soft_delete_node(node.id, user_id="deleter")

    restored = service.restore_node(node.id, user_id="restorer")
    assert restored.deleted_at is None
    assert restored.updated_by == "restorer"

    # 再次恢复保持幂等
    restored_again = service.restore_node(node.id, user_id="restorer")
    assert restored_again.deleted_at is None
