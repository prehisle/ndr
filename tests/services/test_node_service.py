from __future__ import annotations

import pytest

from app.app.services import (
    DocumentCreateData,
    DocumentService,
    MissingUserError,
    NodeConflictError,
    NodeCreateData,
    NodeNotFoundError,
    NodeService,
    NodeUpdateData,
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
    other_root = service.create_node(
        NodeCreateData(name="Other", slug="other", parent_path=None), user_id="u1"
    )
    child = service.create_node(
        NodeCreateData(name="Child", slug="child", parent_path=root.path),
        user_id="u1",
    )
    grand = service.create_node(
        NodeCreateData(name="Grand", slug="grand", parent_path=child.path),
        user_id="u1",
    )

    updated = service.update_node(
        child.id, NodeUpdateData(slug="kid"), user_id="u2"
    )
    assert updated.path == "root.kid"
    assert service.get_node(grand.id).path == "root.kid.grand"

    moved = service.update_node(
        child.id,
        NodeUpdateData(parent_path=other_root.path, parent_path_set=True),
        user_id="u3",
    )
    assert moved.path == "other.kid"
    assert service.get_node(grand.id).path == "other.kid.grand"

    depth_one = service.list_children(other_root.id, depth=1)
    assert {node.id for node in depth_one} == {child.id}

    depth_two = service.list_children(other_root.id, depth=2)
    assert {node.id for node in depth_two} == {child.id, grand.id}


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
        NodeCreateData(name="Child", slug="child", parent_path=root.path), user_id="author"
    )

    doc_root = document_service.create_document(
        DocumentCreateData(title="Root Doc", metadata={"type": "root"}), user_id="author"
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
