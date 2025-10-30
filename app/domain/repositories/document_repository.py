from __future__ import annotations

from typing import Iterable, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.infra.db.models import Document

from .document_filters import MetadataFilters, apply_document_filters


class DocumentRepository:
    def __init__(self, session: Session):
        self._session = session

    def get(self, document_id: int) -> Document | None:
        return self._session.get(Document, document_id)

    def next_position(self, doc_type: str | None) -> int:
        stmt = select(func.max(Document.position))
        if doc_type is None:
            stmt = stmt.where(Document.type.is_(None))
        else:
            stmt = stmt.where(Document.type == doc_type)
        max_pos = self._session.execute(stmt).scalar_one_or_none()
        return 0 if max_pos is None else int(max_pos) + 1

    def paginate_documents(
        self,
        page: int,
        size: int,
        include_deleted: bool,
        *,
        deleted_only: bool = False,
        metadata_filters: MetadataFilters | None = None,
        search_query: str | None = None,
        doc_type: str | None = None,
        doc_ids: Sequence[int] | None = None,
    ) -> tuple[list[Document], int]:
        base_stmt = select(Document)
        count_stmt = select(func.count()).select_from(Document)
        if deleted_only:
            base_stmt = base_stmt.where(Document.deleted_at.is_not(None))
            count_stmt = count_stmt.where(Document.deleted_at.is_not(None))
        elif not include_deleted:
            base_stmt = base_stmt.where(Document.deleted_at.is_(None))
            count_stmt = count_stmt.where(Document.deleted_at.is_(None))

        base_stmt = apply_document_filters(
            base_stmt,
            metadata_filters=metadata_filters,
            search_query=search_query,
        )
        count_stmt = apply_document_filters(
            count_stmt,
            metadata_filters=metadata_filters,
            search_query=search_query,
        )
        if doc_type is not None:
            base_stmt = base_stmt.where(Document.type == doc_type)
            count_stmt = count_stmt.where(Document.type == doc_type)
        if doc_ids:
            base_stmt = base_stmt.where(Document.id.in_(doc_ids))
            count_stmt = count_stmt.where(Document.id.in_(doc_ids))
        base_stmt = base_stmt.order_by(Document.position.asc(), Document.id.asc())
        base_stmt = base_stmt.offset((page - 1) * size).limit(size)
        items = list(self._session.execute(base_stmt).scalars())
        total = self._session.execute(count_stmt).scalar_one()
        return items, total

    def list_by_ids(
        self, document_ids: Sequence[int], include_deleted: bool = False
    ) -> list[Document]:
        if not document_ids:
            return []
        stmt = select(Document).where(Document.id.in_(document_ids))
        if not include_deleted:
            stmt = stmt.where(Document.deleted_at.is_(None))
        stmt = stmt.order_by(Document.position.asc(), Document.id.asc())
        return list(self._session.execute(stmt).scalars())

    def fetch_active_for_reorder(
        self,
        *,
        filter_type: bool,
        doc_type: str | None = None,
    ) -> Sequence[Document]:
        stmt = select(Document).where(Document.deleted_at.is_(None))
        if filter_type:
            if doc_type is None:
                stmt = stmt.where(Document.type.is_(None))
            else:
                stmt = stmt.where(Document.type == doc_type)
        stmt = stmt.order_by(Document.position.asc(), Document.id.asc())
        return tuple(self._session.execute(stmt).scalars())

    def lock_documents(self, document_ids: Iterable[int]) -> None:
        ids = sorted(set(document_ids))
        if not ids:
            return
        for doc_id in ids:
            self._session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": doc_id}
            )
