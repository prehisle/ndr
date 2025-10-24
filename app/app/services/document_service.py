from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.app.services.base import BaseService
from app.app.services.document_version_service import (
    DocumentVersionNotFoundError,
    DocumentVersionService,
)
from app.domain.repositories import DocumentRepository
from app.infra.db.models import Document, NodeDocument


class DocumentNotFoundError(Exception):
    """Raised when the requested document does not exist or is soft-deleted."""


@dataclass(frozen=True)
class DocumentCreateData:
    title: str
    metadata: Optional[dict[str, Any]] = None
    content: Optional[dict[str, Any]] = None
    type: Optional[str] = None
    position: Optional[int] = None


@dataclass(frozen=True)
class DocumentUpdateData:
    title: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    content: Optional[dict[str, Any]] = None
    type: Optional[str] = None
    position: Optional[int] = None


class DocumentService(BaseService):
    """Application service orchestrating document lifecycle operations."""

    def __init__(
        self,
        session: Session,
        repository: DocumentRepository | None = None,
        version_service: DocumentVersionService | None = None,
    ):
        super().__init__(session)
        self._repo = repository or DocumentRepository(session)
        self._versions = version_service or DocumentVersionService(session)

    def create_document(self, data: DocumentCreateData, *, user_id: str) -> Document:
        user = self._ensure_user(user_id)
        payload = dict(data.metadata) if data.metadata is not None else {}
        content = dict(data.content) if data.content is not None else {}
        # 计算 position（如果未提供），按 type 分组递增
        position = data.position
        if position is None:
            position = self._repo.next_position(data.type)
        document = Document(
            title=data.title,
            metadata_=payload,
            content=content,
            type=data.type,
            position=position,
            created_by=user,
            updated_by=user,
        )
        self.session.add(document)
        self.session.flush()
        snapshot = self._versions.build_snapshot_from_document(document)
        self._versions.record_snapshot(snapshot, user_id=user, operation="create")
        self._commit()
        self.session.refresh(document)
        return document

    def get_document(
        self, document_id: int, *, include_deleted: bool = False
    ) -> Document:
        document = self._repo.get(document_id)
        if not document or (document.deleted_at is not None and not include_deleted):
            raise DocumentNotFoundError("Document not found")
        return document

    def update_document(
        self, document_id: int, data: DocumentUpdateData, *, user_id: str
    ) -> Document:
        user = self._ensure_user(user_id)
        document = self._repo.get(document_id)
        if not document or document.deleted_at is not None:
            raise DocumentNotFoundError("Document not found")
        if data.title is not None:
            document.title = data.title
        if data.metadata is not None:
            document.metadata_ = dict(data.metadata)
        if data.content is not None:
            document.content = dict(data.content)
        if data.type is not None:
            document.type = data.type
        if data.position is not None:
            document.position = int(data.position)
        document.updated_by = user
        self.session.flush()
        snapshot = self._versions.build_snapshot_from_document(document)
        self._versions.record_snapshot(snapshot, user_id=user, operation="update")
        self._commit()
        self.session.refresh(document)
        return document

    def soft_delete_document(self, document_id: int, *, user_id: str) -> None:
        user = self._ensure_user(user_id)
        document = self._repo.get(document_id)
        if not document or document.deleted_at is not None:
            raise DocumentNotFoundError("Document not found or already deleted")
        document.deleted_at = datetime.now(timezone.utc)
        document.updated_by = user
        self._commit()

    def list_documents(
        self,
        *,
        page: int,
        size: int,
        include_deleted: bool = False,
        metadata_filters: Mapping[str, Sequence[str]] | None = None,
        search_query: str | None = None,
        doc_type: str | None = None,
        doc_ids: Sequence[int] | None = None,
    ) -> tuple[list[Document], int]:
        return self._repo.paginate_documents(
            page,
            size,
            include_deleted,
            metadata_filters=metadata_filters,
            search_query=search_query,
            doc_type=doc_type,
            doc_ids=doc_ids,
        )

    def list_deleted_documents(
        self,
        *,
        page: int,
        size: int,
        metadata_filters: Mapping[str, Sequence[str]] | None = None,
        search_query: str | None = None,
        doc_type: str | None = None,
        doc_ids: Sequence[int] | None = None,
    ) -> tuple[list[Document], int]:
        return self._repo.paginate_documents(
            page,
            size,
            include_deleted=True,
            deleted_only=True,
            metadata_filters=metadata_filters,
            search_query=search_query,
            doc_type=doc_type,
            doc_ids=doc_ids,
        )

    def restore_document(self, document_id: int, *, user_id: str) -> Document:
        user = self._ensure_user(user_id)
        document = self._repo.get(document_id)
        if not document:
            raise DocumentNotFoundError("Document not found")
        if document.deleted_at is None:
            return document
        document.deleted_at = None
        document.updated_by = user
        document.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        snapshot = self._versions.build_snapshot_from_document(document)
        self._versions.record_snapshot(snapshot, user_id=user, operation="restore-soft")
        self._commit()
        self.session.refresh(document)
        return document

    def purge_document(self, document_id: int, *, user_id: str) -> None:
        self._ensure_user(user_id)
        document = self._repo.get(document_id)
        if not document:
            raise DocumentNotFoundError("Document not found")
        if document.deleted_at is None:
            raise DocumentNotFoundError(
                "Document must be soft-deleted before permanent removal"
            )

        self.session.execute(
            delete(NodeDocument).where(NodeDocument.document_id == document_id)
        )
        self.session.delete(document)
        self._commit()

    def restore_document_version(
        self, document_id: int, version_number: int, *, user_id: str
    ) -> Document:
        user = self._ensure_user(user_id)
        document = self._repo.get(document_id)
        if not document:
            raise DocumentNotFoundError("Document not found")
        try:
            target_version = self._versions.get_version(document_id, version_number)
        except DocumentVersionNotFoundError as exc:
            raise DocumentNotFoundError(str(exc)) from exc

        # Capture current state before mutation
        current_snapshot = self._versions.build_snapshot_from_document(document)
        self._versions.record_snapshot(
            current_snapshot, user_id=user, operation="pre-restore"
        )

        target_snapshot = self._versions.snapshot_from_version(target_version)
        document.title = target_snapshot.title
        document.metadata_ = dict(target_snapshot.metadata)
        document.content = dict(target_snapshot.content)
        document.deleted_at = None
        document.updated_by = user
        document.updated_at = datetime.now(timezone.utc)

        self.session.flush()
        restored_snapshot = self._versions.build_snapshot_from_document(document)
        change_summary = self._versions.diff_snapshots(
            current_snapshot, target_snapshot
        )
        self._versions.record_snapshot(
            restored_snapshot,
            user_id=user,
            operation="restore",
            source_version_number=version_number,
            change_summary=change_summary or None,
        )
        self._commit()
        self.session.refresh(document)
        return document
