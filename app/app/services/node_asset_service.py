"""Node-Asset relationship service.

This module provides the application service layer for managing
the many-to-many relationship between nodes and file assets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Sequence

from sqlalchemy.orm import Session

from app.app.services.asset_service import AssetNotFoundError
from app.app.services.base import BaseService
from app.app.services.node_service import NodeNotFoundError
from app.domain.repositories.node_asset_repository import NodeAssetRepository
from app.domain.repositories.node_repository import NodeRepository
from app.infra.db.models import Asset, NodeAsset


class NodeAssetRelationshipNotFoundError(Exception):
    """Raised when the node-asset relationship does not exist."""


@dataclass(slots=True)
class AssetBinding:
    """Information about an asset's binding to a node."""

    node_id: int
    node_name: str
    node_path: str
    created_at: datetime


@dataclass(slots=True)
class AssetBindingSummary:
    """Summary of an asset's bindings."""

    total_bindings: int
    node_ids: list[int]


class NodeAssetService(BaseService):
    """Application service for managing node-asset relationships.

    Handles binding, unbinding, and querying the relationships
    between nodes and file assets.
    """

    def __init__(
        self,
        session: Session,
        *,
        node_repository: NodeRepository | None = None,
        relationship_repository: NodeAssetRepository | None = None,
    ) -> None:
        super().__init__(session)
        self._nodes = node_repository or NodeRepository(session)
        self._relationships = relationship_repository or NodeAssetRepository(session)

    def _require_active_asset(self, asset_id: int) -> Asset:
        """Get an active (non-deleted) asset or raise an error."""
        asset = self.session.get(Asset, asset_id)
        if not asset or asset.deleted_at is not None:
            raise AssetNotFoundError("Asset not found")
        return asset

    def bind(self, node_id: int, asset_id: int, *, user_id: str) -> NodeAsset:
        """Bind an asset to a node.

        If the relationship already exists (even if soft-deleted),
        it will be restored.

        Args:
            node_id: The node's primary key.
            asset_id: The asset's primary key.
            user_id: ID of the user performing the operation.

        Returns:
            The NodeAsset relationship entity.

        Raises:
            NodeNotFoundError: If the node doesn't exist.
            AssetNotFoundError: If the asset doesn't exist.
        """
        user = self._ensure_user(user_id)

        node = self._nodes.get(node_id)
        if not node or node.deleted_at is not None:
            raise NodeNotFoundError("Node not found")

        self._require_active_asset(asset_id)

        # Check for existing relationship
        relation = self._relationships.get(node_id, asset_id)
        if relation:
            if relation.deleted_at is None:
                return relation
            # Restore soft-deleted relationship
            relation.deleted_at = None
            relation.updated_by = user
            self._commit()
            self.session.refresh(relation)
            return relation

        # Create new relationship
        relation = NodeAsset(
            node_id=node_id,
            asset_id=asset_id,
            created_by=user,
            updated_by=user,
        )
        self.session.add(relation)
        self._commit()
        self.session.refresh(relation)
        return relation

    def unbind(self, node_id: int, asset_id: int, *, user_id: str) -> None:
        """Unbind an asset from a node (soft-delete the relationship).

        Args:
            node_id: The node's primary key.
            asset_id: The asset's primary key.
            user_id: ID of the user performing the operation.

        Raises:
            NodeAssetRelationshipNotFoundError: If the relationship doesn't exist.
        """
        user = self._ensure_user(user_id)

        relation = self._relationships.get(node_id, asset_id)
        if not relation or relation.deleted_at is not None:
            raise NodeAssetRelationshipNotFoundError("Relationship not found")

        relation.deleted_at = datetime.now(timezone.utc)
        relation.updated_by = user
        self._commit()

    def list(
        self,
        *,
        node_id: int | None = None,
        asset_id: int | None = None,
    ) -> list[NodeAsset]:
        """List active node-asset relationships.

        Args:
            node_id: Optional filter by node ID.
            asset_id: Optional filter by asset ID.

        Returns:
            List of active NodeAsset relationships.
        """
        return self._relationships.list_active(node_id=node_id, asset_id=asset_id)

    def list_bindings_for_asset(self, asset_id: int) -> List[AssetBinding]:
        """List all nodes an asset is bound to.

        Args:
            asset_id: The asset's primary key.

        Returns:
            List of AssetBinding objects with node information.

        Raises:
            AssetNotFoundError: If the asset doesn't exist.
        """
        self._require_active_asset(asset_id)
        rows = self._relationships.list_nodes_for_asset(asset_id)
        return [
            AssetBinding(
                node_id=node.id,
                node_name=node.name,
                node_path=node.path,
                created_at=relation.created_at,
            )
            for relation, node in rows
        ]

    def batch_bind(
        self,
        asset_id: int,
        node_ids: Sequence[int],
        *,
        user_id: str,
    ) -> List[AssetBinding]:
        """Bind an asset to multiple nodes at once.

        Args:
            asset_id: The asset's primary key.
            node_ids: List of node IDs to bind to.
            user_id: ID of the user performing the operation.

        Returns:
            List of all bindings for the asset after the operation.

        Raises:
            AssetNotFoundError: If the asset doesn't exist.
            NodeNotFoundError: If any of the nodes don't exist.
        """
        user = self._ensure_user(user_id)
        self._require_active_asset(asset_id)

        # Deduplicate while preserving order
        ordered_ids = list(dict.fromkeys(node_ids))
        if not ordered_ids:
            return self.list_bindings_for_asset(asset_id)

        # Verify all nodes exist
        nodes = self._nodes.get_many(ordered_ids)
        node_map = {node.id: node for node in nodes if node.deleted_at is None}
        missing = [nid for nid in ordered_ids if nid not in node_map]
        if missing:
            raise NodeNotFoundError(f"Nodes not found: {missing}")

        # Create or restore relationships
        for node_id in ordered_ids:
            relation = self._relationships.get(node_id, asset_id)
            if relation is None:
                relation = NodeAsset(
                    node_id=node_id,
                    asset_id=asset_id,
                    created_by=user,
                    updated_by=user,
                )
                self.session.add(relation)
            elif relation.deleted_at is not None:
                relation.deleted_at = None
                relation.updated_by = user

        self._commit()
        return self.list_bindings_for_asset(asset_id)

    def binding_status(self, asset_id: int) -> AssetBindingSummary:
        """Get a summary of an asset's bindings.

        Args:
            asset_id: The asset's primary key.

        Returns:
            AssetBindingSummary with count and list of node IDs.

        Raises:
            AssetNotFoundError: If the asset doesn't exist.
        """
        self._require_active_asset(asset_id)
        node_ids = self._relationships.list_active_node_ids_for_asset(asset_id)
        return AssetBindingSummary(
            total_bindings=len(node_ids),
            node_ids=node_ids,
        )

    def list_assets_for_node(self, node_id: int) -> List[Asset]:
        """List all assets bound to a node.

        Args:
            node_id: The node's primary key.

        Returns:
            List of Asset entities bound to the node.

        Raises:
            NodeNotFoundError: If the node doesn't exist.
        """
        node = self._nodes.get(node_id)
        if not node or node.deleted_at is not None:
            raise NodeNotFoundError("Node not found")

        return self._relationships.list_assets_for_node(node_id)
