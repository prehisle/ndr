from __future__ import annotations

from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infra.db.models import DocumentVersion


class DocumentVersionRepository:
    def __init__(self, session: Session):
        self._session = session

    def create(self, version: DocumentVersion) -> None:
        self._session.add(version)

    def list_by_document(
        self,
        document_id: int,
        *,
        limit: int,
        offset: int,
    ) -> list[DocumentVersion]:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars())

    def count_by_document(self, document_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
        )
        return self._session.execute(stmt).scalar_one()

    def get_by_document_and_number(
        self, document_id: int, version_number: int
    ) -> DocumentVersion | None:
        stmt = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.version_number == version_number,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_latest_version_number(self, document_id: int) -> int | None:
        stmt = select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == document_id
        )
        result = self._session.execute(stmt).scalar_one()
        return result if result is not None else None

    def list_by_ids(self, version_ids: Sequence[int]) -> list[DocumentVersion]:
        if not version_ids:
            return []
        stmt = select(DocumentVersion).where(DocumentVersion.id.in_(version_ids))
        return list(self._session.execute(stmt).scalars())
