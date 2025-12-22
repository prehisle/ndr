"""S3-compatible storage client implementation.

This module provides an S3-compatible storage client that works with
AWS S3, MinIO, and other S3-compatible object storage services.

Dependencies:
    - boto3
    - botocore
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from app.infra.storage.client import (
    CompletedPart,
    MultipartUpload,
    ObjectHead,
    StorageError,
)

if TYPE_CHECKING:
    from app.common.config import Settings


class S3StorageClient:
    """S3-compatible object storage client.

    Supports AWS S3, MinIO, and other S3-compatible services.
    Uses boto3 for all storage operations.
    """

    def __init__(self, *, settings: "Settings") -> None:
        """Initialize the S3 client with configuration from settings.

        Args:
            settings: Application settings containing S3 configuration.

        Raises:
            StorageError: If boto3 is not installed.
        """
        self._settings = settings
        self._client = self._build_client(settings)

    @staticmethod
    def _build_client(settings: "Settings") -> Any:
        """Create a boto3 S3 client from settings."""
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise StorageError(
                "boto3 and botocore are required for S3 storage backend. "
                "Install with: pip install boto3"
            ) from exc

        addressing_style = (settings.S3_ADDRESSING_STYLE or "path").strip().lower()
        config = Config(s3={"addressing_style": addressing_style})

        return boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            use_ssl=bool(settings.S3_USE_SSL),
            config=config,
        )

    def init_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> MultipartUpload:
        """Initialize a multipart upload session."""
        params: dict[str, Any] = {"Bucket": bucket, "Key": object_key}
        if content_type:
            params["ContentType"] = content_type
        if metadata:
            params["Metadata"] = metadata

        try:
            response = self._client.create_multipart_upload(**params)
        except Exception as exc:
            raise StorageError(f"Failed to create multipart upload: {exc}") from exc

        upload_id = response.get("UploadId")
        if not upload_id:
            raise StorageError("S3 response missing UploadId")

        return MultipartUpload(
            upload_id=str(upload_id),
            bucket=bucket,
            object_key=object_key,
        )

    def presign_upload_part(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        part_number: int,
        expires_in: int,
    ) -> str:
        """Generate a presigned URL for uploading a part."""
        try:
            url = self._client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": bucket,
                    "Key": object_key,
                    "UploadId": upload_id,
                    "PartNumber": int(part_number),
                },
                ExpiresIn=int(expires_in),
            )
        except Exception as exc:
            raise StorageError(f"Failed to generate presigned URL: {exc}") from exc

        if not url:
            raise StorageError("Generated presigned URL is empty")

        return str(url)

    def complete_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        parts: Sequence[CompletedPart],
    ) -> None:
        """Complete a multipart upload by combining all parts."""
        multipart_payload = {
            "Parts": [
                {"ETag": part.etag, "PartNumber": int(part.part_number)}
                for part in sorted(parts, key=lambda p: p.part_number)
            ]
        }

        try:
            self._client.complete_multipart_upload(
                Bucket=bucket,
                Key=object_key,
                UploadId=upload_id,
                MultipartUpload=multipart_payload,
            )
        except Exception as exc:
            raise StorageError(f"Failed to complete multipart upload: {exc}") from exc

    def abort_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
    ) -> None:
        """Abort a multipart upload and clean up uploaded parts."""
        try:
            self._client.abort_multipart_upload(
                Bucket=bucket,
                Key=object_key,
                UploadId=upload_id,
            )
        except Exception as exc:
            raise StorageError(f"Failed to abort multipart upload: {exc}") from exc

    def head_object(self, *, bucket: str, object_key: str) -> ObjectHead:
        """Get object metadata without downloading the content."""
        try:
            response = self._client.head_object(Bucket=bucket, Key=object_key)
        except Exception as exc:
            raise StorageError(f"Failed to get object metadata: {exc}") from exc

        size = response.get("ContentLength")
        return ObjectHead(
            size_bytes=int(size) if size is not None else 0,
            etag=response.get("ETag"),
            content_type=response.get("ContentType"),
        )

    def presign_download(
        self,
        *,
        bucket: str,
        object_key: str,
        expires_in: int,
        filename: str | None = None,
    ) -> str:
        """Generate a presigned URL for downloading an object."""
        params: dict[str, Any] = {"Bucket": bucket, "Key": object_key}
        if filename:
            # Escape quotes in filename for Content-Disposition header
            safe_filename = filename.replace('"', '\\"')
            params["ResponseContentDisposition"] = (
                f'attachment; filename="{safe_filename}"'
            )

        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=int(expires_in),
            )
        except Exception as exc:
            raise StorageError(f"Failed to generate download URL: {exc}") from exc

        if not url:
            raise StorageError("Generated presigned URL is empty")

        return str(url)

    def delete_object(self, *, bucket: str, object_key: str) -> None:
        """Delete an object from storage."""
        try:
            self._client.delete_object(Bucket=bucket, Key=object_key)
        except Exception as exc:
            raise StorageError(f"Failed to delete object: {exc}") from exc
