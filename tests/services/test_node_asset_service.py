"""Tests for NodeAssetService."""

from __future__ import annotations

import pytest

from app.app.services.asset_service import (
    AssetMultipartInitData,
    AssetNotFoundError,
    AssetService,
)
from app.app.services.base import MissingUserError
from app.app.services.node_asset_service import (
    NodeAssetRelationshipNotFoundError,
    NodeAssetService,
)
from app.app.services.node_service import NodeCreateData, NodeNotFoundError, NodeService
from app.infra.db.session import get_session_factory
from tests.services.mock_storage import MockStorageClient


@pytest.fixture()
def session():
    session_factory = get_session_factory()
    with session_factory() as session:
        yield session
        session.rollback()


@pytest.fixture()
def mock_storage():
    return MockStorageClient()


@pytest.fixture()
def node_service(session):
    return NodeService(session)


@pytest.fixture()
def asset_service(session, mock_storage):
    return AssetService(session, storage_client=mock_storage)


@pytest.fixture()
def node_asset_service(session):
    return NodeAssetService(session)


def _create_node(node_service, name: str, slug: str, parent_path=None, user_id="u1"):
    """Helper to create a node."""
    return node_service.create_node(
        NodeCreateData(name=name, slug=slug, parent_path=parent_path),
        user_id=user_id,
    )


def _create_asset(asset_service, filename: str, user_id="u1"):
    """Helper to create an asset."""
    data = AssetMultipartInitData(
        filename=filename,
        content_type="application/octet-stream",
        size_bytes=1024,
    )
    result = asset_service.create_multipart_upload(data, user_id=user_id)
    return result.asset


class TestBind:
    def test_binds_asset_to_node(
        self, session, node_service, asset_service, node_asset_service
    ):
        node = _create_node(node_service, "Root", "root")
        asset = _create_asset(asset_service, "test.pdf")

        relation = node_asset_service.bind(node.id, asset.id, user_id="u1")

        assert relation.node_id == node.id
        assert relation.asset_id == asset.id
        assert relation.deleted_at is None

    def test_returns_existing_relation_if_already_bound(
        self, session, node_service, asset_service, node_asset_service
    ):
        node = _create_node(node_service, "Root", "root")
        asset = _create_asset(asset_service, "test.pdf")

        relation1 = node_asset_service.bind(node.id, asset.id, user_id="u1")
        relation2 = node_asset_service.bind(node.id, asset.id, user_id="u1")

        assert relation1.node_id == relation2.node_id
        assert relation1.asset_id == relation2.asset_id

    def test_restores_soft_deleted_relation(
        self, session, node_service, asset_service, node_asset_service
    ):
        node = _create_node(node_service, "Root", "root")
        asset = _create_asset(asset_service, "test.pdf")

        node_asset_service.bind(node.id, asset.id, user_id="u1")
        node_asset_service.unbind(node.id, asset.id, user_id="u1")
        relation = node_asset_service.bind(node.id, asset.id, user_id="u1")

        assert relation.deleted_at is None

    def test_raises_for_nonexistent_node(
        self, session, asset_service, node_asset_service
    ):
        asset = _create_asset(asset_service, "test.pdf")

        with pytest.raises(NodeNotFoundError):
            node_asset_service.bind(99999, asset.id, user_id="u1")

    def test_raises_for_nonexistent_asset(
        self, session, node_service, node_asset_service
    ):
        node = _create_node(node_service, "Root", "root")

        with pytest.raises(AssetNotFoundError):
            node_asset_service.bind(node.id, 99999, user_id="u1")

    def test_requires_user(
        self, session, node_service, asset_service, node_asset_service
    ):
        node = _create_node(node_service, "Root", "root")
        asset = _create_asset(asset_service, "test.pdf")

        with pytest.raises(MissingUserError):
            node_asset_service.bind(node.id, asset.id, user_id="")


class TestUnbind:
    def test_soft_deletes_relation(
        self, session, node_service, asset_service, node_asset_service
    ):
        node = _create_node(node_service, "Root", "root")
        asset = _create_asset(asset_service, "test.pdf")

        node_asset_service.bind(node.id, asset.id, user_id="u1")
        node_asset_service.unbind(node.id, asset.id, user_id="u1")

        relations = node_asset_service.list(node_id=node.id)
        assert len(relations) == 0

    def test_raises_for_nonexistent_relation(
        self, session, node_service, asset_service, node_asset_service
    ):
        node = _create_node(node_service, "Root", "root")
        asset = _create_asset(asset_service, "test.pdf")

        with pytest.raises(NodeAssetRelationshipNotFoundError):
            node_asset_service.unbind(node.id, asset.id, user_id="u1")

    def test_raises_for_already_unbound(
        self, session, node_service, asset_service, node_asset_service
    ):
        node = _create_node(node_service, "Root", "root")
        asset = _create_asset(asset_service, "test.pdf")

        node_asset_service.bind(node.id, asset.id, user_id="u1")
        node_asset_service.unbind(node.id, asset.id, user_id="u1")

        with pytest.raises(NodeAssetRelationshipNotFoundError):
            node_asset_service.unbind(node.id, asset.id, user_id="u1")


class TestList:
    def test_lists_relations_by_node(
        self, session, node_service, asset_service, node_asset_service
    ):
        node1 = _create_node(node_service, "Node1", "node1")
        node2 = _create_node(node_service, "Node2", "node2")
        asset1 = _create_asset(asset_service, "asset1.pdf")
        asset2 = _create_asset(asset_service, "asset2.pdf")

        node_asset_service.bind(node1.id, asset1.id, user_id="u1")
        node_asset_service.bind(node1.id, asset2.id, user_id="u1")
        node_asset_service.bind(node2.id, asset1.id, user_id="u1")

        relations = node_asset_service.list(node_id=node1.id)

        assert len(relations) == 2

    def test_lists_relations_by_asset(
        self, session, node_service, asset_service, node_asset_service
    ):
        node1 = _create_node(node_service, "Node1", "node1")
        node2 = _create_node(node_service, "Node2", "node2")
        asset = _create_asset(asset_service, "test.pdf")

        node_asset_service.bind(node1.id, asset.id, user_id="u1")
        node_asset_service.bind(node2.id, asset.id, user_id="u1")

        relations = node_asset_service.list(asset_id=asset.id)

        assert len(relations) == 2


class TestListBindingsForAsset:
    def test_returns_binding_info(
        self, session, node_service, asset_service, node_asset_service
    ):
        root = _create_node(node_service, "Root", "root")
        child = _create_node(node_service, "Child", "child", parent_path="root")
        asset = _create_asset(asset_service, "test.pdf")

        node_asset_service.bind(root.id, asset.id, user_id="u1")
        node_asset_service.bind(child.id, asset.id, user_id="u1")

        bindings = node_asset_service.list_bindings_for_asset(asset.id)

        assert len(bindings) == 2
        assert bindings[0].node_name == "Root"
        assert bindings[0].node_path == "root"
        assert bindings[1].node_name == "Child"
        assert bindings[1].node_path == "root.child"

    def test_raises_for_nonexistent_asset(self, node_asset_service):
        with pytest.raises(AssetNotFoundError):
            node_asset_service.list_bindings_for_asset(99999)


class TestBatchBind:
    def test_binds_to_multiple_nodes(
        self, session, node_service, asset_service, node_asset_service
    ):
        node1 = _create_node(node_service, "Node1", "node1")
        node2 = _create_node(node_service, "Node2", "node2")
        node3 = _create_node(node_service, "Node3", "node3")
        asset = _create_asset(asset_service, "test.pdf")

        bindings = node_asset_service.batch_bind(
            asset.id, [node1.id, node2.id, node3.id], user_id="u1"
        )

        assert len(bindings) == 3
        node_ids = {b.node_id for b in bindings}
        assert node_ids == {node1.id, node2.id, node3.id}

    def test_deduplicates_node_ids(
        self, session, node_service, asset_service, node_asset_service
    ):
        node = _create_node(node_service, "Node", "node")
        asset = _create_asset(asset_service, "test.pdf")

        bindings = node_asset_service.batch_bind(
            asset.id, [node.id, node.id, node.id], user_id="u1"
        )

        assert len(bindings) == 1

    def test_raises_for_nonexistent_node(
        self, session, node_service, asset_service, node_asset_service
    ):
        node = _create_node(node_service, "Node", "node")
        asset = _create_asset(asset_service, "test.pdf")

        with pytest.raises(NodeNotFoundError, match="99999"):
            node_asset_service.batch_bind(asset.id, [node.id, 99999], user_id="u1")


class TestBindingStatus:
    def test_returns_summary(
        self, session, node_service, asset_service, node_asset_service
    ):
        node1 = _create_node(node_service, "Node1", "node1")
        node2 = _create_node(node_service, "Node2", "node2")
        asset = _create_asset(asset_service, "test.pdf")

        node_asset_service.bind(node1.id, asset.id, user_id="u1")
        node_asset_service.bind(node2.id, asset.id, user_id="u1")

        status = node_asset_service.binding_status(asset.id)

        assert status.total_bindings == 2
        assert set(status.node_ids) == {node1.id, node2.id}


class TestListAssetsForNode:
    def test_returns_assets_for_node(
        self, session, node_service, asset_service, node_asset_service
    ):
        node = _create_node(node_service, "Node", "node")
        asset1 = _create_asset(asset_service, "asset1.pdf")
        asset2 = _create_asset(asset_service, "asset2.pdf")

        node_asset_service.bind(node.id, asset1.id, user_id="u1")
        node_asset_service.bind(node.id, asset2.id, user_id="u1")

        assets = node_asset_service.list_assets_for_node(node.id)

        assert len(assets) == 2
        filenames = {a.filename for a in assets}
        assert filenames == {"asset1.pdf", "asset2.pdf"}

    def test_raises_for_nonexistent_node(self, node_asset_service):
        with pytest.raises(NodeNotFoundError):
            node_asset_service.list_assets_for_node(99999)

    def test_excludes_deleted_assets(
        self, session, node_service, asset_service, node_asset_service
    ):
        node = _create_node(node_service, "Node", "node")
        asset1 = _create_asset(asset_service, "asset1.pdf")
        asset2 = _create_asset(asset_service, "asset2.pdf")

        node_asset_service.bind(node.id, asset1.id, user_id="u1")
        node_asset_service.bind(node.id, asset2.id, user_id="u1")

        asset_service.soft_delete_asset(asset2.id, user_id="u1")

        assets = node_asset_service.list_assets_for_node(node.id)

        assert len(assets) == 1
        assert assets[0].filename == "asset1.pdf"
