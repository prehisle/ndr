from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from app.app.services.base import BaseService
from app.app.services.document_service import DocumentNotFoundError
from app.app.services.node_service import NodeNotFoundError
from app.domain.repositories import NodeRepository, RelationshipRepository
from app.infra.db.models import Document, NodeDocument


class RelationshipNotFoundError(Exception):
    """Raised when the node-document relationship does not exist."""


@dataclass(slots=True)
class DocumentBinding:
    node_id: int
    node_name: str
    node_path: str
    created_at: datetime


@dataclass(slots=True)
class DocumentBindingSummary:
    total_bindings: int
    node_ids: List[int]


class RelationshipService(BaseService):
    """Application service orchestrating node-document relationship use cases."""

    def __init__(
        self,
        session: Session,
        *,
        node_repository: NodeRepository | None = None,
        relationship_repository: RelationshipRepository | None = None,
    ):
        super().__init__(session)
        self._nodes = node_repository or NodeRepository(session)
        self._relationships = relationship_repository or RelationshipRepository(session)

    def _require_active_document(self, document_id: int) -> Document:
        document = self.session.get(Document, document_id)
        if not document or document.deleted_at is not None:
            raise DocumentNotFoundError("Document not found")
        return document

    def bind(self, node_id: int, document_id: int, *, user_id: str) -> NodeDocument:
        user = self._ensure_user(user_id)
        node = self._nodes.get(node_id)
        if not node or node.deleted_at is not None:
            raise NodeNotFoundError("Node not found")

        self._require_active_document(document_id)

        relation = self._relationships.get(node_id, document_id)
        if relation:
            if relation.deleted_at is None:
                return relation
            relation.deleted_at = None
            relation.updated_by = user
            self._commit()
            self.session.refresh(relation)
            return relation

        relation = NodeDocument(
            node_id=node_id,
            document_id=document_id,
            created_by=user,
            updated_by=user,
        )
        self.session.add(relation)
        self._commit()
        self.session.refresh(relation)
        return relation

    def unbind(self, node_id: int, document_id: int, *, user_id: str) -> None:
        user = self._ensure_user(user_id)
        relation = self._relationships.get(node_id, document_id)
        if not relation or relation.deleted_at is not None:
            raise RelationshipNotFoundError("Relation not found")
        relation.deleted_at = datetime.now(timezone.utc)
        relation.updated_by = user
        self._commit()

    def list(
        self, *, node_id: Optional[int] = None, document_id: Optional[int] = None
    ) -> List[NodeDocument]:
        return self._relationships.list_active(node_id=node_id, document_id=document_id)

    def list_bindings_for_document(self, document_id: int) -> List[DocumentBinding]:
        self._require_active_document(document_id)
        rows = self._relationships.list_nodes_for_document(document_id)
        return [
            DocumentBinding(
                node_id=node.id,
                node_name=node.name,
                node_path=node.path,
                created_at=relation.created_at,
            )
            for relation, node in rows
        ]

    def batch_bind(
        self, document_id: int, node_ids: Sequence[int], *, user_id: str
    ) -> List[DocumentBinding]:
        user = self._ensure_user(user_id)
        self._require_active_document(document_id)

        ordered_ids = list(dict.fromkeys(node_ids))
        if not ordered_ids:
            return self.list_bindings_for_document(document_id)

        nodes = self._nodes.get_many(ordered_ids)
        node_map = {node.id: node for node in nodes if node.deleted_at is None}
        missing = [node_id for node_id in ordered_ids if node_id not in node_map]
        if missing:
            raise NodeNotFoundError("Node not found")

        for node_id in ordered_ids:
            relation = self._relationships.get(node_id, document_id)
            if relation is None:
                relation = NodeDocument(
                    node_id=node_id,
                    document_id=document_id,
                    created_by=user,
                    updated_by=user,
                )
                self.session.add(relation)
                continue
            if relation.deleted_at is not None:
                relation.deleted_at = None
                relation.updated_by = user
        self._commit()
        return self.list_bindings_for_document(document_id)

    def binding_status(self, document_id: int) -> DocumentBindingSummary:
        self._require_active_document(document_id)
        node_ids = self._relationships.list_active_node_ids_for_document(document_id)
        return DocumentBindingSummary(
            total_bindings=len(node_ids),
            node_ids=node_ids,
        )
