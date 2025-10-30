from __future__ import annotations

import pytest

from app.app.services import (
    DocumentCreateData,
    DocumentNotFoundError,
    DocumentReorderData,
    DocumentService,
    DocumentUpdateData,
    DocumentVersionService,
    MissingUserError,
    NodeCreateData,
    NodeService,
    RelationshipService,
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
        DocumentCreateData(
            title="Spec",
            metadata={"type": "spec"},
            content={"body": "initial"},
        ),
        user_id="creator",
    )
    assert created.metadata_ == {"type": "spec"}
    assert created.content == {"body": "initial"}
    assert created.created_by == "creator"
    assert created.version_number == 1

    fetched = service.get_document(created.id)
    assert fetched.id == created.id
    assert fetched.version_number == 1

    updated = service.update_document(
        created.id,
        DocumentUpdateData(
            title="Spec v2",
            metadata={"type": "spec", "version": 2},
            content={"body": "updated"},
        ),
        user_id="editor",
    )
    assert updated.title == "Spec v2"
    assert updated.metadata_["version"] == 2
    assert updated.content == {"body": "updated"}
    assert updated.updated_by == "editor"
    assert updated.version_number == 2

    items, total = service.list_documents(page=1, size=10)
    assert total == 1
    assert items[0].id == created.id
    assert items[0].version_number == 2

    service.soft_delete_document(created.id, user_id="deleter")

    with pytest.raises(DocumentNotFoundError):
        service.get_document(created.id)

    deleted = service.get_document(created.id, include_deleted=True)
    assert deleted.deleted_at is not None
    assert deleted.version_number == 2

    trash_items, trash_total = service.list_deleted_documents(page=1, size=10)
    assert trash_total == 1
    assert trash_items[0].id == created.id
    assert trash_items[0].version_number == 2


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


def test_document_service_restore(session):
    service = DocumentService(session)
    created = service.create_document(
        DocumentCreateData(title="Spec", metadata={}, content={}),
        user_id="author",
    )

    service.soft_delete_document(created.id, user_id="deleter")
    restored = service.restore_document(created.id, user_id="restorer")
    assert restored.deleted_at is None
    assert restored.updated_by == "restorer"

    # 再次恢复应保持幂等
    restored_again = service.restore_document(created.id, user_id="restorer")
    assert restored_again.deleted_at is None


def test_document_version_history_and_restore(session):
    service = DocumentService(session)
    version_service = DocumentVersionService(session)

    doc = service.create_document(
        DocumentCreateData(
            title="Versioned Spec",
            metadata={"stage": "draft"},
            content={"body": "v1"},
        ),
        user_id="author",
    )

    doc = service.update_document(
        doc.id,
        DocumentUpdateData(
            title="Versioned Spec v2",
            metadata={"stage": "final", "approved": True},
            content={"body": "v2"},
        ),
        user_id="editor",
    )

    versions, total = version_service.list_versions(doc.id, page=1, size=10)
    assert total == 2
    version_numbers = {version.version_number for version in versions}
    assert version_numbers == {1, 2}
    latest = max(versions, key=lambda v: v.version_number)
    earliest = min(versions, key=lambda v: v.version_number)

    diff = version_service.diff_versions(earliest, latest)
    assert diff["title"]["to"] == "Versioned Spec v2"
    assert diff["metadata"]["added"]["approved"] is True
    assert diff["content"]["changed"]["body"]["to"] == "v2"

    restored = service.restore_document_version(doc.id, 1, user_id="restorer")
    assert restored.title == "Versioned Spec"
    assert restored.metadata_ == {"stage": "draft"}
    assert restored.content == {"body": "v1"}


def test_purge_document_requires_soft_delete(session):
    document_service = DocumentService(session)
    node_service = NodeService(session)
    relationship_service = RelationshipService(session)

    document = document_service.create_document(
        DocumentCreateData(title="Doc", metadata={}, content={}),
        user_id="owner",
    )
    node = node_service.create_node(
        NodeCreateData(name="Root", slug="root", parent_path=None), user_id="owner"
    )
    relationship_service.bind(node.id, document.id, user_id="owner")

    with pytest.raises(DocumentNotFoundError):
        document_service.purge_document(document.id, user_id="admin")

    document_service.soft_delete_document(document.id, user_id="deleter")
    document_service.purge_document(document.id, user_id="admin")

    with pytest.raises(DocumentNotFoundError):
        document_service.get_document(document.id, include_deleted=True)
    assert relationship_service.list(document_id=document.id) == []


def test_list_documents_filters_by_ids_and_type(session):
    service = DocumentService(session)

    d1 = service.create_document(
        DocumentCreateData(title="D1", metadata={}, content={}, type="spec"),
        user_id="u",
    )
    d2 = service.create_document(
        DocumentCreateData(title="D2", metadata={}, content={}, type="note"),
        user_id="u",
    )
    d3 = service.create_document(
        DocumentCreateData(title="D3", metadata={}, content={}, type="spec"),
        user_id="u",
    )

    # 按类型过滤
    items_spec, total_spec = service.list_documents(page=1, size=10, doc_type="spec")
    assert total_spec == 2
    assert {d.id for d in items_spec} == {d1.id, d3.id}

    # 按 ID 过滤
    items_ids, total_ids = service.list_documents(
        page=1, size=10, doc_ids=(d1.id, d2.id)
    )
    assert total_ids == 2
    assert {d.id for d in items_ids} == {d1.id, d2.id}

    # 组合过滤：类型 + ID，仅返回交集
    items_combo, total_combo = service.list_documents(
        page=1, size=10, doc_type="spec", doc_ids=(d2.id, d3.id)
    )
    assert total_combo == 1
    assert {d.id for d in items_combo} == {d3.id}


def test_reorder_documents_does_not_create_versions(session):
    service = DocumentService(session)
    version_service = DocumentVersionService(session)

    guide_a = service.create_document(
        DocumentCreateData(title="Guide A", metadata={}, content={}, type="guide"),
        user_id="author",
    )
    guide_b = service.create_document(
        DocumentCreateData(title="Guide B", metadata={}, content={}, type="guide"),
        user_id="author",
    )
    note = service.create_document(
        DocumentCreateData(title="Note", metadata={}, content={}, type="note"),
        user_id="author",
    )

    reordered_guides = service.reorder_documents(
        DocumentReorderData(
            ordered_ids=(guide_b.id, guide_a.id),
            doc_type="guide",
            apply_type_filter=True,
        ),
        user_id="moderator",
    )
    assert [doc.id for doc in reordered_guides] == [guide_b.id, guide_a.id]

    for doc in (guide_a, guide_b, note):
        session.refresh(doc)

    assert guide_b.position == 0
    assert guide_a.position == 1
    assert note.position == 0

    reordered_all = service.reorder_documents(
        DocumentReorderData(ordered_ids=(note.id, guide_a.id)),
        user_id="admin",
    )
    assert [doc.id for doc in reordered_all] == [note.id, guide_a.id, guide_b.id]

    for doc in (guide_a, guide_b, note):
        session.refresh(doc)

    assert note.position == 0
    assert guide_a.position == 1
    assert guide_b.position == 2

    assert version_service.get_latest_version_number(guide_a.id) == 1
    assert version_service.get_latest_version_number(guide_b.id) == 1
    assert version_service.get_latest_version_number(note.id) == 1
