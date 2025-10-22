from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.db.models import Document, NodeDocument


class RelationshipRepository:
    def __init__(self, session: Session):
        self._session = session

    def get(self, node_id: int, document_id: int) -> NodeDocument | None:
        stmt = select(NodeDocument).where(
            NodeDocument.node_id == node_id,
            NodeDocument.document_id == document_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_active(
        self,
        *,
        node_id: Optional[int] = None,
        document_id: Optional[int] = None,
    ) -> list[NodeDocument]:
        stmt = select(NodeDocument).where(NodeDocument.deleted_at.is_(None))
        if node_id is not None:
            stmt = stmt.where(NodeDocument.node_id == node_id)
        if document_id is not None:
            stmt = stmt.where(NodeDocument.document_id == document_id)
        return list(self._session.execute(stmt).scalars())

    def list_documents_for_nodes(
        self,
        node_ids: Sequence[int],
        *,
        include_deleted_relations: bool = False,
        include_deleted_documents: bool = False,
    ) -> list[Document]:
        if not node_ids:
            return []
        stmt = (
            select(Document)
            .join(NodeDocument, NodeDocument.document_id == Document.id)
            .where(NodeDocument.node_id.in_(node_ids))
            .distinct()
            .order_by(Document.position.asc(), Document.id.asc())
        )
        if not include_deleted_relations:
            stmt = stmt.where(NodeDocument.deleted_at.is_(None))
        if not include_deleted_documents:
            stmt = stmt.where(Document.deleted_at.is_(None))
        return list(self._session.execute(stmt).scalars())
