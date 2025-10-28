from __future__ import annotations

import pytest

from app.app.services import (
    DocumentNotFoundError,
    MissingUserError,
    NodeCreateData,
    NodeNotFoundError,
    NodeService,
    RelationshipNotFoundError,
    RelationshipService,
)
from app.infra.db.models import Document
from app.infra.db.session import get_session_factory


@pytest.fixture()
def session():
    session_factory = get_session_factory()
    with session_factory() as session:
        yield session
        session.rollback()


def _document(session, title: str, user_id: str = "u1") -> Document:
    doc = Document(
        title=title,
        metadata_={},
        content={},
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def test_relationship_bind_unbind_and_rebind(session):
    node_service = NodeService(session)
    relationship_service = RelationshipService(session)

    node = node_service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="owner"
    )
    document = _document(session, "Doc A", user_id="owner")

    relation = relationship_service.bind(node.id, document.id, user_id="user")
    assert relation.node_id == node.id
    assert relation.document_id == document.id

    rebound = relationship_service.bind(node.id, document.id, user_id="user")
    assert rebound.node_id == node.id
    assert rebound.document_id == document.id

    relationship_service.unbind(node.id, document.id, user_id="user")
    assert relationship_service.list(node_id=node.id) == []

    with pytest.raises(RelationshipNotFoundError):
        relationship_service.unbind(node.id, document.id, user_id="user")

    reopened = relationship_service.bind(node.id, document.id, user_id="user")
    assert reopened.node_id == node.id


def test_bind_validates_document_existence(session):
    node_service = NodeService(session)
    relationship_service = RelationshipService(session)

    node = node_service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="owner"
    )

    with pytest.raises(DocumentNotFoundError):
        relationship_service.bind(node.id, document_id=9999, user_id="owner")


def test_relationship_service_requires_user(session):
    node_service = NodeService(session)
    relationship_service = RelationshipService(session)

    node = node_service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="owner"
    )
    document = _document(session, "Doc A", user_id="owner")

    with pytest.raises(MissingUserError):
        relationship_service.bind(node.id, document.id, user_id="")

    relationship_service.bind(node.id, document.id, user_id="owner")

    with pytest.raises(MissingUserError):
        relationship_service.unbind(node.id, document.id, user_id="")


def test_list_bindings_and_status(session):
    node_service = NodeService(session)
    relationship_service = RelationshipService(session)

    root = node_service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="owner"
    )
    child = node_service.create_node(
        NodeCreateData(name="Child", slug="child", parent_path=root.path),
        user_id="owner",
    )
    document = _document(session, "Doc A", user_id="owner")

    relationship_service.bind(root.id, document.id, user_id="owner")
    relationship_service.bind(child.id, document.id, user_id="owner")

    bindings = relationship_service.list_bindings_for_document(document.id)
    assert [b.node_id for b in bindings] == [root.id, child.id]
    assert bindings[0].node_name == "Root"
    assert bindings[1].node_path == "root.child"

    status = relationship_service.binding_status(document.id)
    assert status.total_bindings == 2
    assert status.node_ids == [root.id, child.id]

    node_service.soft_delete_node(child.id, user_id="owner")
    bindings_after = relationship_service.list_bindings_for_document(document.id)
    assert [b.node_id for b in bindings_after] == [root.id]
    status_after = relationship_service.binding_status(document.id)
    assert status_after.total_bindings == 1
    assert status_after.node_ids == [root.id]


def test_batch_bind_behaviour(session):
    node_service = NodeService(session)
    relationship_service = RelationshipService(session)

    root = node_service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="owner"
    )
    child = node_service.create_node(
        NodeCreateData(name="Child", slug="child", parent_path=root.path),
        user_id="owner",
    )
    document = _document(session, "Doc A", user_id="owner")

    bindings = relationship_service.batch_bind(
        document.id, [root.id, child.id, root.id], user_id="owner"
    )
    assert {b.node_id for b in bindings} == {root.id, child.id}

    # 再次绑定保持结果不变
    bindings_repeat = relationship_service.batch_bind(
        document.id, [child.id], user_id="owner"
    )
    assert {b.node_id for b in bindings_repeat} == {root.id, child.id}

    # 解绑后批量绑定可恢复
    relationship_service.unbind(child.id, document.id, user_id="owner")
    bindings_reopen = relationship_service.batch_bind(
        document.id, [child.id], user_id="owner"
    )
    assert {b.node_id for b in bindings_reopen} == {root.id, child.id}


def test_batch_bind_validates_inputs(session):
    node_service = NodeService(session)
    relationship_service = RelationshipService(session)

    root = node_service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="owner"
    )
    document = _document(session, "Doc A", user_id="owner")

    with pytest.raises(DocumentNotFoundError):
        relationship_service.batch_bind(9999, [root.id], user_id="owner")

    with pytest.raises(MissingUserError):
        relationship_service.batch_bind(document.id, [root.id], user_id="")

    with pytest.raises(DocumentNotFoundError):
        relationship_service.list_bindings_for_document(9999)

    with pytest.raises(DocumentNotFoundError):
        relationship_service.binding_status(9999)

    node_service.soft_delete_node(root.id, user_id="owner")
    with pytest.raises(NodeNotFoundError):
        relationship_service.batch_bind(document.id, [root.id], user_id="owner")
