from __future__ import annotations

import pytest

from app.app.services import (
    DocumentCreateData,
    DocumentNotFoundError,
    DocumentService,
    DocumentUpdateData,
    MissingUserError,
)
from app.infra.db.session import get_session_factory


@pytest.fixture()
def session():
    session_factory = get_session_factory()
    with session_factory() as session:
        yield session
        session.rollback()


def test_document_service_crud_flow(session):
    service = DocumentService(session)

    created = service.create_document(
        DocumentCreateData(title="Spec", metadata={"type": "spec"}),
        user_id="creator",
    )
    assert created.metadata_ == {"type": "spec"}
    assert created.created_by == "creator"

    fetched = service.get_document(created.id)
    assert fetched.id == created.id

    updated = service.update_document(
        created.id,
        DocumentUpdateData(title="Spec v2", metadata={"type": "spec", "version": 2}),
        user_id="editor",
    )
    assert updated.title == "Spec v2"
    assert updated.metadata_["version"] == 2
    assert updated.updated_by == "editor"

    items, total = service.list_documents(page=1, size=10)
    assert total == 1
    assert items[0].id == created.id

    service.soft_delete_document(created.id, user_id="deleter")

    with pytest.raises(DocumentNotFoundError):
        service.get_document(created.id)

    deleted = service.get_document(created.id, include_deleted=True)
    assert deleted.deleted_at is not None


def test_document_service_guards_and_not_found(session):
    service = DocumentService(session)

    with pytest.raises(MissingUserError):
        service.create_document(DocumentCreateData(title="Spec"), user_id="")

    with pytest.raises(DocumentNotFoundError):
        service.update_document(
            999,
            DocumentUpdateData(title="missing"),
            user_id="tester",
        )

    with pytest.raises(DocumentNotFoundError):
        service.soft_delete_document(999, user_id="tester")
