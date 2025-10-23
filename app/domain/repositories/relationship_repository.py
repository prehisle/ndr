from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infra.db.models import Document, NodeDocument

from .document_filters import MetadataFilters, apply_document_filters


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
        metadata_filters: MetadataFilters | None = None,
        search_query: str | None = None,
        doc_type: str | None = None,
        doc_ids: Sequence[int] | None = None,
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
        if doc_type is not None:
            stmt = stmt.where(Document.type == doc_type)
        if doc_ids:
            stmt = stmt.where(Document.id.in_(doc_ids))
        stmt = apply_document_filters(
            stmt,
            metadata_filters=metadata_filters,
            search_query=search_query,
        )
        return list(self._session.execute(stmt).scalars())

    def paginate_documents_for_nodes(
        self,
        node_ids: Sequence[int],
        *,
        page: int,
        size: int,
        include_deleted_relations: bool = False,
        include_deleted_documents: bool = False,
        metadata_filters: MetadataFilters | None = None,
        search_query: str | None = None,
        doc_type: str | None = None,
        doc_ids: Sequence[int] | None = None,
    ) -> tuple[list[Document], int]:
        if not node_ids:
            return [], 0
        # Base count query
        count_stmt = (
            select(func.count(func.distinct(Document.id)))
            .join(NodeDocument, NodeDocument.document_id == Document.id)
            .where(NodeDocument.node_id.in_(node_ids))
        )
        if not include_deleted_relations:
            count_stmt = count_stmt.where(NodeDocument.deleted_at.is_(None))
        if not include_deleted_documents:
            count_stmt = count_stmt.where(Document.deleted_at.is_(None))
        if doc_type is not None:
            count_stmt = count_stmt.where(Document.type == doc_type)
        if doc_ids:
            count_stmt = count_stmt.where(Document.id.in_(doc_ids))
        count_stmt = apply_document_filters(
            count_stmt,
            metadata_filters=metadata_filters,
            search_query=search_query,
        )
        total = self._session.execute(count_stmt).scalar_one()

        # Items query with ordering and pagination
        items_stmt = (
            select(Document)
            .join(NodeDocument, NodeDocument.document_id == Document.id)
            .where(NodeDocument.node_id.in_(node_ids))
            .distinct()
            .order_by(Document.position.asc(), Document.id.asc())
        )
        if not include_deleted_relations:
            items_stmt = items_stmt.where(NodeDocument.deleted_at.is_(None))
        if not include_deleted_documents:
            items_stmt = items_stmt.where(Document.deleted_at.is_(None))
        if doc_type is not None:
            items_stmt = items_stmt.where(Document.type == doc_type)
        if doc_ids:
            items_stmt = items_stmt.where(Document.id.in_(doc_ids))
        items_stmt = (
            apply_document_filters(
                items_stmt,
                metadata_filters=metadata_filters,
                search_query=search_query,
            )
            .offset((page - 1) * size)
            .limit(size)
        )

        items = list(self._session.execute(items_stmt).scalars())
        return items, total
