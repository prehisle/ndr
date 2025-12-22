from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.domain.repositories import (
    AssetRepository,
    DocumentRepository,
    DocumentVersionRepository,
    NodeAssetRepository,
    NodeRepository,
    RelationshipRepository,
)

from .asset_service import AssetService
from .document_service import DocumentService
from .document_version_service import DocumentVersionService
from .node_asset_service import NodeAssetService
from .node_service import NodeService
from .relationship_service import RelationshipService


@dataclass
class ServiceBundle:
    """Lazily constructs application services sharing the same session."""

    session: Session
    _document: DocumentService | None = field(default=None, init=False, repr=False)
    _document_version: DocumentVersionService | None = field(
        default=None, init=False, repr=False
    )
    _node: NodeService | None = field(default=None, init=False, repr=False)
    _relationship: RelationshipService | None = field(
        default=None, init=False, repr=False
    )
    _asset: AssetService | None = field(default=None, init=False, repr=False)
    _node_asset: NodeAssetService | None = field(default=None, init=False, repr=False)

    def document(self) -> DocumentService:
        if self._document is None:
            repo = DocumentRepository(self.session)
            version_service = self.document_version()
            self._document = DocumentService(
                self.session,
                repository=repo,
                version_service=version_service,
            )
        return self._document

    def document_version(self) -> DocumentVersionService:
        if self._document_version is None:
            version_repo = DocumentVersionRepository(self.session)
            self._document_version = DocumentVersionService(
                self.session, repository=version_repo
            )
        return self._document_version

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

    def asset(self) -> AssetService:
        if self._asset is None:
            repo = AssetRepository(self.session)
            self._asset = AssetService(self.session, repository=repo)
        return self._asset

    def node_asset(self) -> NodeAssetService:
        if self._node_asset is None:
            node_repo = NodeRepository(self.session)
            rel_repo = NodeAssetRepository(self.session)
            self._node_asset = NodeAssetService(
                self.session,
                node_repository=node_repo,
                relationship_repository=rel_repo,
            )
        return self._node_asset


def get_service_bundle(session: Session) -> ServiceBundle:
    return ServiceBundle(session=session)
