"""API tests for asset endpoints."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app

from tests.services.mock_storage import MockStorageClient


def _make_client_with_mock_storage():
    """Create a test client with mocked storage."""
    mock_storage = MockStorageClient()

    app = create_app()
    client = TestClient(app)

    return client, mock_storage


def _init_multipart(client, filename="test.pdf", size_bytes=10 * 1024 * 1024):
    """Helper to initialize a multipart upload."""
    payload = {
        "filename": filename,
        "content_type": "application/pdf",
        "size_bytes": size_bytes,
    }
    return client.post(
        "/api/v1/assets/multipart/init",
        json=payload,
        headers={"X-User-Id": "u1"},
    )


def _create_node(client, name, slug, parent_path=None):
    """Helper to create a node."""
    payload = {"name": name, "slug": slug}
    if parent_path:
        payload["parent_path"] = parent_path
    resp = client.post("/api/v1/nodes", json=payload, headers={"X-User-Id": "u1"})
    assert resp.status_code == 201
    return resp.json()


class TestInitMultipartUpload:
    def test_creates_asset_and_returns_upload_info(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            resp = _init_multipart(client)

            assert resp.status_code == 201
            data = resp.json()
            assert "asset" in data
            assert data["asset"]["filename"] == "test.pdf"
            assert data["asset"]["status"] == "UPLOADING"
            assert "upload_id" in data
            assert data["upload_id"].startswith("mock-upload-")
            assert data["part_size_bytes"] > 0
            assert data["expires_in"] > 0

    def test_uses_missing_user_when_no_header(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            payload = {
                "filename": "test.pdf",
                "content_type": "application/pdf",
                "size_bytes": 1024,
            }
            resp = client.post("/api/v1/assets/multipart/init", json=payload)

            # The API allows requests without X-User-Id, using "<missing>" as the user
            assert resp.status_code == 201
            assert resp.json()["asset"]["created_by"] == "<missing>"

    def test_validates_size_bytes(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            payload = {
                "filename": "test.pdf",
                "content_type": "application/pdf",
                "size_bytes": 0,
            }
            resp = client.post(
                "/api/v1/assets/multipart/init",
                json=payload,
                headers={"X-User-Id": "u1"},
            )

            assert resp.status_code == 422


class TestPresignUploadParts:
    def test_returns_presigned_urls(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            init_resp = _init_multipart(client)
            asset_id = init_resp.json()["asset"]["id"]

            resp = client.post(
                f"/api/v1/assets/{asset_id}/multipart/part-urls",
                json={"part_numbers": [1, 2, 3]},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert len(data["urls"]) == 3
            assert data["upload_id"].startswith("mock-upload-")

    def test_returns_404_for_nonexistent_asset(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            resp = client.post(
                "/api/v1/assets/99999/multipart/part-urls",
                json={"part_numbers": [1]},
            )

            assert resp.status_code == 404


class TestCompleteMultipartUpload:
    def test_completes_upload(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            init_resp = _init_multipart(client)
            asset_id = init_resp.json()["asset"]["id"]

            resp = client.post(
                f"/api/v1/assets/{asset_id}/multipart/complete",
                json={"parts": [{"part_number": 1, "etag": "etag1"}]},
                headers={"X-User-Id": "u1"},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "READY"

    def test_rejects_empty_parts(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            init_resp = _init_multipart(client)
            asset_id = init_resp.json()["asset"]["id"]

            resp = client.post(
                f"/api/v1/assets/{asset_id}/multipart/complete",
                json={"parts": []},
                headers={"X-User-Id": "u1"},
            )

            assert resp.status_code == 422


class TestAbortMultipartUpload:
    def test_aborts_upload(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            init_resp = _init_multipart(client)
            asset_id = init_resp.json()["asset"]["id"]

            resp = client.post(
                f"/api/v1/assets/{asset_id}/multipart/abort",
                headers={"X-User-Id": "u1"},
            )

            assert resp.status_code == 204

            # Verify status is ABORTED
            get_resp = client.get(f"/api/v1/assets/{asset_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["status"] == "ABORTED"


class TestGetAsset:
    def test_returns_asset(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            init_resp = _init_multipart(client)
            asset_id = init_resp.json()["asset"]["id"]

            resp = client.get(f"/api/v1/assets/{asset_id}")

            assert resp.status_code == 200
            assert resp.json()["id"] == asset_id

    def test_returns_404_for_nonexistent(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            resp = client.get("/api/v1/assets/99999")

            assert resp.status_code == 404


class TestListAssets:
    def test_returns_paginated_list(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            for i in range(3):
                _init_multipart(client, filename=f"file{i}.pdf")

            resp = client.get("/api/v1/assets?page=1&size=10")

            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 3
            assert len(data["items"]) == 3


class TestSoftDeleteAsset:
    def test_deletes_asset(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            init_resp = _init_multipart(client)
            asset_id = init_resp.json()["asset"]["id"]

            resp = client.delete(
                f"/api/v1/assets/{asset_id}",
                headers={"X-User-Id": "u1"},
            )

            assert resp.status_code == 204

            # Verify asset is deleted
            get_resp = client.get(f"/api/v1/assets/{asset_id}")
            assert get_resp.status_code == 404


class TestGetDownloadUrl:
    def test_returns_download_url(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            init_resp = _init_multipart(client)
            asset_id = init_resp.json()["asset"]["id"]

            # Complete upload first
            client.post(
                f"/api/v1/assets/{asset_id}/multipart/complete",
                json={"parts": [{"part_number": 1, "etag": "etag1"}]},
                headers={"X-User-Id": "u1"},
            )

            resp = client.get(f"/api/v1/assets/{asset_id}/download-url")

            assert resp.status_code == 200
            data = resp.json()
            assert "url" in data
            assert "download=true" in data["url"]

    def test_rejects_non_ready_asset(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            init_resp = _init_multipart(client)
            asset_id = init_resp.json()["asset"]["id"]

            resp = client.get(f"/api/v1/assets/{asset_id}/download-url")

            assert resp.status_code == 400


class TestNodeAssetBinding:
    def test_bind_and_unbind(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            node = _create_node(client, "Root", "root")
            init_resp = _init_multipart(client)
            asset_id = init_resp.json()["asset"]["id"]

            # Bind
            bind_resp = client.post(
                f"/api/v1/nodes/{node['id']}/assets/{asset_id}",
                headers={"X-User-Id": "u1"},
            )
            assert bind_resp.status_code == 201

            # List bindings
            bindings_resp = client.get(f"/api/v1/assets/{asset_id}/bindings")
            assert bindings_resp.status_code == 200
            assert len(bindings_resp.json()) == 1

            # Unbind
            unbind_resp = client.delete(
                f"/api/v1/nodes/{node['id']}/assets/{asset_id}",
                headers={"X-User-Id": "u1"},
            )
            assert unbind_resp.status_code == 204

    def test_batch_bind(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            node1 = _create_node(client, "Node1", "node1")
            node2 = _create_node(client, "Node2", "node2")
            init_resp = _init_multipart(client)
            asset_id = init_resp.json()["asset"]["id"]

            resp = client.post(
                f"/api/v1/assets/{asset_id}/batch-bind",
                json={"node_ids": [node1["id"], node2["id"]]},
                headers={"X-User-Id": "u1"},
            )

            assert resp.status_code == 200
            assert len(resp.json()) == 2

    def test_binding_status(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            node = _create_node(client, "Root", "root")
            init_resp = _init_multipart(client)
            asset_id = init_resp.json()["asset"]["id"]

            client.post(
                f"/api/v1/nodes/{node['id']}/assets/{asset_id}",
                headers={"X-User-Id": "u1"},
            )

            resp = client.get(f"/api/v1/assets/{asset_id}/binding-status")

            assert resp.status_code == 200
            data = resp.json()
            assert data["total_bindings"] == 1
            assert node["id"] in data["node_ids"]

    def test_list_node_assets(self):
        with patch(
            "app.app.services.asset_service.AssetService._build_storage_client",
            return_value=MockStorageClient(),
        ):
            app = create_app()
            client = TestClient(app)

            node = _create_node(client, "Root", "root")
            init_resp1 = _init_multipart(client, filename="file1.pdf")
            init_resp2 = _init_multipart(client, filename="file2.pdf")
            asset1_id = init_resp1.json()["asset"]["id"]
            asset2_id = init_resp2.json()["asset"]["id"]

            # Bind both assets
            client.post(
                f"/api/v1/nodes/{node['id']}/assets/{asset1_id}",
                headers={"X-User-Id": "u1"},
            )
            client.post(
                f"/api/v1/nodes/{node['id']}/assets/{asset2_id}",
                headers={"X-User-Id": "u1"},
            )

            resp = client.get(f"/api/v1/nodes/{node['id']}/assets")

            assert resp.status_code == 200
            assets = resp.json()
            assert len(assets) == 2
            filenames = {a["filename"] for a in assets}
            assert filenames == {"file1.pdf", "file2.pdf"}
