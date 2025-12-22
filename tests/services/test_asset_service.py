"""Tests for AssetService."""

from __future__ import annotations

import pytest

from app.app.services.asset_service import (
    AssetMultipartInitData,
    AssetNotFoundError,
    AssetService,
    InvalidAssetOperationError,
)
from app.app.services.base import MissingUserError
from app.infra.db.session import get_session_factory
from app.infra.storage.client import CompletedPart
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
def asset_service(session, mock_storage):
    return AssetService(session, storage_client=mock_storage)


class TestCreateMultipartUpload:
    def test_creates_asset_and_initiates_upload(
        self, session, asset_service, mock_storage
    ):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=10 * 1024 * 1024,  # 10MB
        )

        result = asset_service.create_multipart_upload(data, user_id="u1")

        assert result.asset.id is not None
        assert result.asset.filename == "test.pdf"
        assert result.asset.content_type == "application/pdf"
        assert result.asset.size_bytes == 10 * 1024 * 1024
        assert result.asset.status == "UPLOADING"
        assert result.upload_id.startswith("mock-upload-")
        assert result.part_size_bytes > 0
        assert result.expires_in > 0

    def test_sanitizes_filename(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="path/to/file.txt",
            content_type="text/plain",
            size_bytes=1024,
        )

        result = asset_service.create_multipart_upload(data, user_id="u1")

        assert result.asset.filename == "path_to_file.txt"

    def test_rejects_zero_size(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.txt",
            content_type="text/plain",
            size_bytes=0,
        )

        with pytest.raises(InvalidAssetOperationError, match="positive"):
            asset_service.create_multipart_upload(data, user_id="u1")

    def test_rejects_negative_size(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.txt",
            content_type="text/plain",
            size_bytes=-100,
        )

        with pytest.raises(InvalidAssetOperationError, match="positive"):
            asset_service.create_multipart_upload(data, user_id="u1")

    def test_requires_user(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.txt",
            content_type="text/plain",
            size_bytes=1024,
        )

        with pytest.raises(MissingUserError):
            asset_service.create_multipart_upload(data, user_id="")


class TestPresignUploadParts:
    def test_generates_presigned_urls(self, session, asset_service, mock_storage):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=50 * 1024 * 1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        upload_id, urls = asset_service.presign_upload_parts(result.asset.id, [1, 2, 3])

        assert upload_id == result.upload_id
        assert len(urls) == 3
        assert urls[0].part_number == 1
        assert urls[1].part_number == 2
        assert urls[2].part_number == 3
        assert all("uploadId=" in u.url for u in urls)

    def test_deduplicates_part_numbers(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=50 * 1024 * 1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        upload_id, urls = asset_service.presign_upload_parts(
            result.asset.id, [1, 2, 2, 3, 1]
        )

        assert len(urls) == 3
        part_numbers = [u.part_number for u in urls]
        assert part_numbers == [1, 2, 3]

    def test_rejects_invalid_part_numbers(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=50 * 1024 * 1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        with pytest.raises(InvalidAssetOperationError, match="between 1 and"):
            asset_service.presign_upload_parts(result.asset.id, [0])

        with pytest.raises(InvalidAssetOperationError, match="between 1 and"):
            asset_service.presign_upload_parts(result.asset.id, [-1])

        with pytest.raises(InvalidAssetOperationError, match="between 1 and"):
            asset_service.presign_upload_parts(result.asset.id, [10001])

    def test_rejects_too_many_parts(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=50 * 1024 * 1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        with pytest.raises(InvalidAssetOperationError, match="1000"):
            asset_service.presign_upload_parts(result.asset.id, list(range(1, 1002)))

    def test_rejects_non_uploading_asset(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=10 * 1024 * 1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        # Complete the upload first
        asset_service.complete_multipart_upload(
            result.asset.id,
            parts=[CompletedPart(part_number=1, etag="etag1")],
            user_id="u1",
        )

        with pytest.raises(InvalidAssetOperationError, match="UPLOADING"):
            asset_service.presign_upload_parts(result.asset.id, [1])

    def test_rejects_nonexistent_asset(self, asset_service):
        with pytest.raises(AssetNotFoundError):
            asset_service.presign_upload_parts(99999, [1])


class TestCompleteMultipartUpload:
    def test_completes_upload_and_updates_status(
        self, session, asset_service, mock_storage
    ):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=10 * 1024 * 1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        parts = [
            CompletedPart(part_number=1, etag="etag1"),
            CompletedPart(part_number=2, etag="etag2"),
        ]
        completed = asset_service.complete_multipart_upload(
            result.asset.id, parts=parts, user_id="u1"
        )

        assert completed.status == "READY"
        assert completed.etag is not None

    def test_rejects_empty_parts(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=10 * 1024 * 1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        with pytest.raises(InvalidAssetOperationError, match="empty"):
            asset_service.complete_multipart_upload(
                result.asset.id, parts=[], user_id="u1"
            )

    def test_rejects_non_uploading_asset(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=10 * 1024 * 1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        parts = [CompletedPart(part_number=1, etag="etag1")]
        asset_service.complete_multipart_upload(
            result.asset.id, parts=parts, user_id="u1"
        )

        with pytest.raises(InvalidAssetOperationError, match="UPLOADING"):
            asset_service.complete_multipart_upload(
                result.asset.id, parts=parts, user_id="u1"
            )

    def test_requires_user(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=10 * 1024 * 1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        parts = [CompletedPart(part_number=1, etag="etag1")]
        with pytest.raises(MissingUserError):
            asset_service.complete_multipart_upload(
                result.asset.id, parts=parts, user_id=""
            )


class TestGetAsset:
    def test_returns_asset_by_id(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        asset = asset_service.get_asset(result.asset.id)

        assert asset.id == result.asset.id
        assert asset.filename == "test.pdf"

    def test_raises_for_nonexistent(self, asset_service):
        with pytest.raises(AssetNotFoundError):
            asset_service.get_asset(99999)

    def test_raises_for_deleted_unless_included(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")
        asset_service.soft_delete_asset(result.asset.id, user_id="u1")

        with pytest.raises(AssetNotFoundError):
            asset_service.get_asset(result.asset.id)

        asset = asset_service.get_asset(result.asset.id, include_deleted=True)
        assert asset.id == result.asset.id


class TestListAssets:
    def test_returns_paginated_assets(self, session, asset_service):
        for i in range(5):
            data = AssetMultipartInitData(
                filename=f"file{i}.txt",
                content_type="text/plain",
                size_bytes=1024,
            )
            asset_service.create_multipart_upload(data, user_id="u1")

        items, total = asset_service.list_assets(page=1, size=3)

        assert len(items) == 3
        assert total == 5

    def test_filters_by_status(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="ready.pdf",
            content_type="application/pdf",
            size_bytes=1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")
        asset_service.complete_multipart_upload(
            result.asset.id,
            parts=[CompletedPart(part_number=1, etag="etag1")],
            user_id="u1",
        )

        data2 = AssetMultipartInitData(
            filename="uploading.pdf",
            content_type="application/pdf",
            size_bytes=1024,
        )
        asset_service.create_multipart_upload(data2, user_id="u1")

        items, total = asset_service.list_assets(page=1, size=10, status="READY")

        assert total == 1
        assert items[0].filename == "ready.pdf"


class TestSoftDeleteAsset:
    def test_marks_asset_as_deleted(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        asset_service.soft_delete_asset(result.asset.id, user_id="u1")

        asset = asset_service.get_asset(result.asset.id, include_deleted=True)
        assert asset.deleted_at is not None
        assert asset.status == "DELETED"

    def test_raises_for_nonexistent(self, session, asset_service):
        with pytest.raises(AssetNotFoundError):
            asset_service.soft_delete_asset(99999, user_id="u1")

    def test_raises_for_already_deleted(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")
        asset_service.soft_delete_asset(result.asset.id, user_id="u1")

        with pytest.raises(AssetNotFoundError, match="already deleted"):
            asset_service.soft_delete_asset(result.asset.id, user_id="u1")


class TestAbortMultipartUpload:
    def test_aborts_upload_and_updates_status(
        self, session, asset_service, mock_storage
    ):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=10 * 1024 * 1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        asset_service.abort_multipart_upload(result.asset.id, user_id="u1")

        asset = asset_service.get_asset(result.asset.id)
        assert asset.status == "ABORTED"
        assert mock_storage.uploads[result.upload_id]["aborted"] is True

    def test_rejects_non_uploading_asset(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=10 * 1024 * 1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        parts = [CompletedPart(part_number=1, etag="etag1")]
        asset_service.complete_multipart_upload(
            result.asset.id, parts=parts, user_id="u1"
        )

        with pytest.raises(InvalidAssetOperationError, match="UPLOADING"):
            asset_service.abort_multipart_upload(result.asset.id, user_id="u1")


class TestPresignDownloadUrl:
    def test_generates_download_url(self, session, asset_service, mock_storage):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")
        asset_service.complete_multipart_upload(
            result.asset.id,
            parts=[CompletedPart(part_number=1, etag="etag1")],
            user_id="u1",
        )

        download = asset_service.presign_download_url(result.asset.id)

        assert "download=true" in download.url
        assert download.expires_in > 0

    def test_rejects_non_ready_asset(self, session, asset_service):
        data = AssetMultipartInitData(
            filename="test.pdf",
            content_type="application/pdf",
            size_bytes=1024,
        )
        result = asset_service.create_multipart_upload(data, user_id="u1")

        with pytest.raises(InvalidAssetOperationError, match="not ready"):
            asset_service.presign_download_url(result.asset.id)
