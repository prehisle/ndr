from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.domain.repositories import DocumentRepository, NodeRepository, RelationshipRepository

from .document_service import DocumentService
from .node_service import NodeService
from .relationship_service import RelationshipService


@dataclass
class ServiceBundle:
    """Lazily constructs application services sharing the same session."""

    session: Session
    _document: DocumentService | None = field(default=None, init=False, repr=False)
    _node: NodeService | None = field(default=None, init=False, repr=False)
    _relationship: RelationshipService | None = field(default=None, init=False, repr=False)

    def document(self) -> DocumentService:
        if self._document is None:
            repo = DocumentRepository(self.session)
            self._document = DocumentService(self.session, repository=repo)
        return self._document

    def node(self) -> NodeService:
        if self._node is None:
            node_repo = NodeRepository(self.session)
            rel_repo = RelationshipRepository(self.session)
            self._node = NodeService(
                self.session,
                repository=node_repo,
                relationship_repository=rel_repo,
            )
        return self._node

    def relationship(self) -> RelationshipService:
        if self._relationship is None:
            node_repo = NodeRepository(self.session)
            rel_repo = RelationshipRepository(self.session)
            self._relationship = RelationshipService(
                self.session,
                node_repository=node_repo,
                relationship_repository=rel_repo,
            )
        return self._relationship


def get_service_bundle(session: Session) -> ServiceBundle:
    return ServiceBundle(session=session)

