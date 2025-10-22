from __future__ import annotations

from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infra.db.models import Document


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
        self, page: int, size: int, include_deleted: bool, doc_type: str | None = None
    ) -> tuple[list[Document], int]:
        base_stmt = select(Document)
        count_stmt = select(func.count()).select_from(Document)
        if not include_deleted:
            base_stmt = base_stmt.where(Document.deleted_at.is_(None))
            count_stmt = count_stmt.where(Document.deleted_at.is_(None))
        if doc_type is not None:
            base_stmt = base_stmt.where(Document.type == doc_type)
            count_stmt = count_stmt.where(Document.type == doc_type)
        base_stmt = (
            base_stmt.order_by(Document.position.asc(), Document.id.asc())
            .offset((page - 1) * size)
            .limit(size)
        )
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
