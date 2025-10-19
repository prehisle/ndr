from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.app.services.base import BaseService
from app.app.services.document_service import DocumentNotFoundError
from app.app.services.node_service import NodeNotFoundError
from app.domain.repositories import NodeRepository, RelationshipRepository
from app.infra.db.models import Document, NodeDocument


class RelationshipNotFoundError(Exception):
    """Raised when the node-document relationship does not exist."""


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

    def bind(
        self, node_id: int, document_id: int, *, user_id: str
    ) -> NodeDocument:
        user = self._ensure_user(user_id)
        node = self._nodes.get(node_id)
        if not node or node.deleted_at is not None:
            raise NodeNotFoundError("Node not found")

        document = self.session.get(Document, document_id)
        if not document or document.deleted_at is not None:
            raise DocumentNotFoundError("Document not found")

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

    def unbind(
        self, node_id: int, document_id: int, *, user_id: str
    ) -> None:
        user = self._ensure_user(user_id)
        relation = self._relationships.get(node_id, document_id)
        if not relation or relation.deleted_at is not None:
            raise RelationshipNotFoundError("Relation not found")
        relation.deleted_at = datetime.now(timezone.utc)
        relation.updated_by = user
        self._commit()

    def list(
        self, *, node_id: Optional[int] = None, document_id: Optional[int] = None
    ) -> list[NodeDocument]:
        return self._relationships.list_active(
            node_id=node_id, document_id=document_id
        )
