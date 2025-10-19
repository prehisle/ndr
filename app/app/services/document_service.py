from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.app.services.base import BaseService
from app.domain.repositories import DocumentRepository
from app.infra.db.models import Document


class DocumentNotFoundError(Exception):
    """Raised when the requested document does not exist or is soft-deleted."""


@dataclass(frozen=True)
class DocumentCreateData:
    title: str
    metadata: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class DocumentUpdateData:
    title: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class DocumentService(BaseService):
    """Application service orchestrating document lifecycle operations."""

    def __init__(self, session: Session, repository: DocumentRepository | None = None):
        super().__init__(session)
        self._repo = repository or DocumentRepository(session)

    def create_document(self, data: DocumentCreateData, *, user_id: str) -> Document:
        user = self._ensure_user(user_id)
        payload = dict(data.metadata) if data.metadata is not None else {}
        document = Document(
            title=data.title,
            metadata_=payload,
            created_by=user,
            updated_by=user,
        )
        self.session.add(document)
        self._commit()
        self.session.refresh(document)
        return document

    def get_document(self, document_id: int, *, include_deleted: bool = False) -> Document:
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
        document.updated_by = user
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
        self, *, page: int, size: int, include_deleted: bool = False
    ) -> tuple[list[Document], int]:
        return self._repo.paginate_documents(page, size, include_deleted)
