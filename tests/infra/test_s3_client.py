"""Tests for S3 storage client."""

from unittest.mock import MagicMock, patch

import pytest

from app.infra.storage.client import CompletedPart, MultipartUpload, StorageError
from app.infra.storage.s3_client import S3StorageClient


class TestS3StorageClient:
    """Test S3StorageClient implementation."""

    @pytest.fixture
    def mock_s3(self):
        """Mock boto3 S3 client."""
        mock_client = MagicMock()
        with patch.object(S3StorageClient, "_build_client", return_value=mock_client):
            yield mock_client

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for S3."""
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.S3_ENDPOINT_URL = "http://localhost:9000"
        settings.S3_REGION = "us-east-1"
        settings.S3_ACCESS_KEY_ID = "test-key"
        settings.S3_SECRET_ACCESS_KEY = "test-secret"
        settings.S3_USE_SSL = False
        settings.S3_ADDRESSING_STYLE = "path"
        return settings

    @pytest.fixture
    def client(self, mock_s3, mock_settings):
        """Create S3StorageClient with mocked boto3."""
        return S3StorageClient(settings=mock_settings)

    def test_init_multipart_upload(self, client, mock_s3):
        """Test initiating multipart upload."""
        mock_s3.create_multipart_upload.return_value = {
            "UploadId": "test-upload-id",
            "Bucket": "test-bucket",
            "Key": "test/key",
        }

        result = client.init_multipart_upload(
            bucket="test-bucket",
            object_key="test/key",
            content_type="application/pdf",
        )

        assert isinstance(result, MultipartUpload)
        assert result.upload_id == "test-upload-id"
        assert result.bucket == "test-bucket"
        assert result.object_key == "test/key"

        mock_s3.create_multipart_upload.assert_called_once_with(
            Bucket="test-bucket",
            Key="test/key",
            ContentType="application/pdf",
        )

    def test_presign_upload_part(self, client, mock_s3):
        """Test presigning upload part URL."""
        mock_s3.generate_presigned_url.return_value = "https://presigned-url"

        url = client.presign_upload_part(
            bucket="test-bucket",
            object_key="test/key",
            upload_id="test-upload-id",
            part_number=1,
            expires_in=900,
        )

        assert url == "https://presigned-url"
        mock_s3.generate_presigned_url.assert_called_once()

    def test_complete_multipart_upload(self, client, mock_s3):
        """Test completing multipart upload."""
        mock_s3.complete_multipart_upload.return_value = {
            "ETag": '"test-etag"',
            "Bucket": "test-bucket",
            "Key": "test/key",
        }

        parts = [
            CompletedPart(part_number=1, etag="etag1"),
            CompletedPart(part_number=2, etag="etag2"),
        ]

        client.complete_multipart_upload(
            bucket="test-bucket",
            object_key="test/key",
            upload_id="test-upload-id",
            parts=parts,
        )

        # Verify the parts are sorted by part_number
        call_args = mock_s3.complete_multipart_upload.call_args
        assert call_args[1]["Bucket"] == "test-bucket"
        assert call_args[1]["Key"] == "test/key"
        assert call_args[1]["UploadId"] == "test-upload-id"
        assert call_args[1]["MultipartUpload"]["Parts"] == [
            {"ETag": "etag1", "PartNumber": 1},
            {"ETag": "etag2", "PartNumber": 2},
        ]

    def test_abort_multipart_upload(self, client, mock_s3):
        """Test aborting multipart upload."""
        client.abort_multipart_upload(
            bucket="test-bucket",
            object_key="test/key",
            upload_id="test-upload-id",
        )

        mock_s3.abort_multipart_upload.assert_called_once_with(
            Bucket="test-bucket",
            Key="test/key",
            UploadId="test-upload-id",
        )

    def test_presign_download(self, client, mock_s3):
        """Test presigning download URL."""
        mock_s3.generate_presigned_url.return_value = "https://download-url"

        url = client.presign_download(
            bucket="test-bucket",
            object_key="test/key",
            expires_in=900,
            filename="download.pdf",
        )

        assert url == "https://download-url"
        mock_s3.generate_presigned_url.assert_called_once()

    def test_presign_download_without_filename(self, client, mock_s3):
        """Test presigning download URL without filename."""
        mock_s3.generate_presigned_url.return_value = "https://download-url"

        url = client.presign_download(
            bucket="test-bucket",
            object_key="test/key",
            expires_in=900,
        )

        assert url == "https://download-url"
        call_args = mock_s3.generate_presigned_url.call_args
        assert "ResponseContentDisposition" not in call_args[1]["Params"]

    def test_head_object(self, client, mock_s3):
        """Test getting object metadata."""
        mock_s3.head_object.return_value = {
            "ContentLength": 1024,
            "ETag": '"test-etag"',
            "ContentType": "application/pdf",
        }

        result = client.head_object(bucket="test-bucket", object_key="test/key")

        assert result.size_bytes == 1024
        assert result.etag == '"test-etag"'
        assert result.content_type == "application/pdf"
        mock_s3.head_object.assert_called_once_with(
            Bucket="test-bucket", Key="test/key"
        )

    def test_head_object_missing_size(self, client, mock_s3):
        """Test getting object metadata when ContentLength is missing."""
        mock_s3.head_object.return_value = {
            "ETag": '"test-etag"',
            "ContentType": "application/pdf",
        }

        result = client.head_object(bucket="test-bucket", object_key="test/key")

        assert result.size_bytes == 0
        assert result.etag == '"test-etag"'

    def test_delete_object(self, client, mock_s3):
        """Test deleting an object."""
        client.delete_object(bucket="test-bucket", object_key="test/key")

        mock_s3.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="test/key"
        )

    def test_init_multipart_upload_missing_upload_id(self, client, mock_s3):
        """Test error when S3 response missing UploadId."""
        mock_s3.create_multipart_upload.return_value = {}

        with pytest.raises(StorageError, match="S3 response missing UploadId"):
            client.init_multipart_upload(
                bucket="test-bucket",
                object_key="test/key",
            )

    def test_init_multipart_upload_exception(self, client, mock_s3):
        """Test error handling when create_multipart_upload fails."""
        mock_s3.create_multipart_upload.side_effect = Exception("S3 error")

        with pytest.raises(StorageError, match="Failed to create multipart upload"):
            client.init_multipart_upload(
                bucket="test-bucket",
                object_key="test/key",
            )

    def test_presign_upload_part_exception(self, client, mock_s3):
        """Test error handling when generate_presigned_url fails."""
        mock_s3.generate_presigned_url.side_effect = Exception("S3 error")

        with pytest.raises(StorageError, match="Failed to generate presigned URL"):
            client.presign_upload_part(
                bucket="test-bucket",
                object_key="test/key",
                upload_id="test-upload-id",
                part_number=1,
                expires_in=900,
            )

    def test_presign_upload_part_empty_url(self, client, mock_s3):
        """Test error when presigned URL is empty."""
        mock_s3.generate_presigned_url.return_value = ""

        with pytest.raises(StorageError, match="Generated presigned URL is empty"):
            client.presign_upload_part(
                bucket="test-bucket",
                object_key="test/key",
                upload_id="test-upload-id",
                part_number=1,
                expires_in=900,
            )

    def test_complete_multipart_upload_exception(self, client, mock_s3):
        """Test error handling when complete_multipart_upload fails."""
        mock_s3.complete_multipart_upload.side_effect = Exception("S3 error")

        with pytest.raises(StorageError, match="Failed to complete multipart upload"):
            client.complete_multipart_upload(
                bucket="test-bucket",
                object_key="test/key",
                upload_id="test-upload-id",
                parts=[CompletedPart(part_number=1, etag="etag1")],
            )

    def test_abort_multipart_upload_exception(self, client, mock_s3):
        """Test error handling when abort_multipart_upload fails."""
        mock_s3.abort_multipart_upload.side_effect = Exception("S3 error")

        with pytest.raises(StorageError, match="Failed to abort multipart upload"):
            client.abort_multipart_upload(
                bucket="test-bucket",
                object_key="test/key",
                upload_id="test-upload-id",
            )

    def test_head_object_exception(self, client, mock_s3):
        """Test error handling when head_object fails."""
        mock_s3.head_object.side_effect = Exception("S3 error")

        with pytest.raises(StorageError, match="Failed to get object metadata"):
            client.head_object(bucket="test-bucket", object_key="test/key")

    def test_presign_download_exception(self, client, mock_s3):
        """Test error handling when presign_download fails."""
        mock_s3.generate_presigned_url.side_effect = Exception("S3 error")

        with pytest.raises(StorageError, match="Failed to generate download URL"):
            client.presign_download(
                bucket="test-bucket",
                object_key="test/key",
                expires_in=900,
            )

    def test_presign_download_empty_url(self, client, mock_s3):
        """Test error when download URL is empty."""
        mock_s3.generate_presigned_url.return_value = ""

        with pytest.raises(StorageError, match="Generated presigned URL is empty"):
            client.presign_download(
                bucket="test-bucket",
                object_key="test/key",
                expires_in=900,
            )

    def test_delete_object_exception(self, client, mock_s3):
        """Test error handling when delete_object fails."""
        mock_s3.delete_object.side_effect = Exception("S3 error")

        with pytest.raises(StorageError, match="Failed to delete object"):
            client.delete_object(bucket="test-bucket", object_key="test/key")
