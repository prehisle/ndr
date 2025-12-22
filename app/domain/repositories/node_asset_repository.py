"""NodeAsset repository for relationship data access.

This module provides the data access layer for Node-Asset relationships,
handling queries for the many-to-many association between nodes and assets.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.db.models import Asset, Node, NodeAsset


class NodeAssetRepository:
    """Repository for NodeAsset relationship database operations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, node_id: int, asset_id: int) -> NodeAsset | None:
        """Get a specific node-asset relationship.

        Args:
            node_id: The node's primary key.
            asset_id: The asset's primary key.

        Returns:
            The NodeAsset relationship if found, None otherwise.
        """
        stmt = select(NodeAsset).where(
            NodeAsset.node_id == node_id,
            NodeAsset.asset_id == asset_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_active(
        self,
        *,
        node_id: int | None = None,
        asset_id: int | None = None,
    ) -> list[NodeAsset]:
        """List active (non-deleted) relationships.

        Args:
            node_id: Optional filter by node ID.
            asset_id: Optional filter by asset ID.

        Returns:
            List of active NodeAsset relationships.
        """
        stmt = select(NodeAsset).where(NodeAsset.deleted_at.is_(None))
        if node_id is not None:
            stmt = stmt.where(NodeAsset.node_id == node_id)
        if asset_id is not None:
            stmt = stmt.where(NodeAsset.asset_id == asset_id)
        return list(self._session.execute(stmt).scalars())

    def list_nodes_for_asset(
        self,
        asset_id: int,
        *,
        include_deleted_relations: bool = False,
        include_deleted_nodes: bool = False,
    ) -> list[tuple[NodeAsset, Node]]:
        """List all nodes associated with an asset.

        Args:
            asset_id: The asset's primary key.
            include_deleted_relations: Include soft-deleted relationships.
            include_deleted_nodes: Include soft-deleted nodes.

        Returns:
            List of (NodeAsset, Node) tuples.
        """
        stmt = (
            select(NodeAsset, Node)
            .join(Node, Node.id == NodeAsset.node_id)
            .where(NodeAsset.asset_id == asset_id)
            .order_by(Node.path.asc(), Node.id.asc())
        )
        if not include_deleted_relations:
            stmt = stmt.where(NodeAsset.deleted_at.is_(None))
        if not include_deleted_nodes:
            stmt = stmt.where(Node.deleted_at.is_(None))

        rows = self._session.execute(stmt).all()
        return [(row[0], row[1]) for row in rows]

    def list_active_node_ids_for_asset(
        self,
        asset_id: int,
        *,
        include_deleted_relations: bool = False,
        include_deleted_nodes: bool = False,
    ) -> list[int]:
        """Get IDs of all active nodes associated with an asset.

        Args:
            asset_id: The asset's primary key.
            include_deleted_relations: Include soft-deleted relationships.
            include_deleted_nodes: Include soft-deleted nodes.

        Returns:
            List of node IDs.
        """
        stmt = (
            select(NodeAsset.node_id)
            .join(Node, Node.id == NodeAsset.node_id)
            .where(NodeAsset.asset_id == asset_id)
            .order_by(NodeAsset.node_id.asc())
        )
        if not include_deleted_relations:
            stmt = stmt.where(NodeAsset.deleted_at.is_(None))
        if not include_deleted_nodes:
            stmt = stmt.where(Node.deleted_at.is_(None))

        return list(self._session.execute(stmt).scalars())

    def list_assets_for_node(
        self,
        node_id: int,
        *,
        include_deleted_relations: bool = False,
        include_deleted_assets: bool = False,
    ) -> list[Asset]:
        """List all assets associated with a node.

        Args:
            node_id: The node's primary key.
            include_deleted_relations: Include soft-deleted relationships.
            include_deleted_assets: Include soft-deleted assets.

        Returns:
            List of Asset entities.
        """
        stmt = (
            select(Asset)
            .join(NodeAsset, NodeAsset.asset_id == Asset.id)
            .where(NodeAsset.node_id == node_id)
            .order_by(Asset.id.asc())
        )
        if not include_deleted_relations:
            stmt = stmt.where(NodeAsset.deleted_at.is_(None))
        if not include_deleted_assets:
            stmt = stmt.where(Asset.deleted_at.is_(None))

        return list(self._session.execute(stmt).scalars())
