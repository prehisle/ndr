from __future__ import annotations

import pytest

from app.app.services import (
    DocumentNotFoundError,
    MissingUserError,
    NodeCreateData,
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
