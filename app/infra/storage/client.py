"""Storage client protocol and data types.

This module defines the abstract interface for object storage operations,
supporting multipart uploads, presigned URLs, and basic object management.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


class StorageError(RuntimeError):
    """Raised when object storage operations fail."""


@dataclass(frozen=True, slots=True)
class CompletedPart:
    """Represents a completed part in a multipart upload."""

    part_number: int
    etag: str


@dataclass(frozen=True, slots=True)
class MultipartUpload:
    """Result of initiating a multipart upload."""

    upload_id: str
    bucket: str
    object_key: str


@dataclass(frozen=True, slots=True)
class ObjectHead:
    """Metadata from a HEAD object request."""

    size_bytes: int
    etag: str | None
    content_type: str | None


class StorageClient(Protocol):
    """Protocol defining the interface for object storage backends.

    Implementations must provide all methods defined here.
    Currently supports S3-compatible storage services.
    """

    def init_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> MultipartUpload:
        """Initialize a multipart upload session.

        Args:
            bucket: Target bucket name.
            object_key: Object key (path) in the bucket.
            content_type: MIME type of the object.
            metadata: Custom metadata to attach to the object.

        Returns:
            MultipartUpload containing the upload_id for subsequent operations.

        Raises:
            StorageError: If the operation fails.
        """
        ...

    def presign_upload_part(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        part_number: int,
        expires_in: int,
    ) -> str:
        """Generate a presigned URL for uploading a part.

        Args:
            bucket: Target bucket name.
            object_key: Object key (path) in the bucket.
            upload_id: Multipart upload ID from init_multipart_upload.
            part_number: Part number (1-based, max 10000).
            expires_in: URL expiration time in seconds.

        Returns:
            Presigned URL for PUT request.

        Raises:
            StorageError: If URL generation fails.
        """
        ...

    def complete_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        parts: Sequence[CompletedPart],
    ) -> None:
        """Complete a multipart upload by combining all parts.

        Args:
            bucket: Target bucket name.
            object_key: Object key (path) in the bucket.
            upload_id: Multipart upload ID.
            parts: List of completed parts with their ETags.

        Raises:
            StorageError: If the operation fails.
        """
        ...

    def abort_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
    ) -> None:
        """Abort a multipart upload and clean up uploaded parts.

        Args:
            bucket: Target bucket name.
            object_key: Object key (path) in the bucket.
            upload_id: Multipart upload ID to abort.

        Raises:
            StorageError: If the operation fails.
        """
        ...

    def head_object(self, *, bucket: str, object_key: str) -> ObjectHead:
        """Get object metadata without downloading the content.

        Args:
            bucket: Target bucket name.
            object_key: Object key (path) in the bucket.

        Returns:
            ObjectHead with size, ETag, and content type.

        Raises:
            StorageError: If the object doesn't exist or operation fails.
        """
        ...

    def presign_download(
        self,
        *,
        bucket: str,
        object_key: str,
        expires_in: int,
        filename: str | None = None,
    ) -> str:
        """Generate a presigned URL for downloading an object.

        Args:
            bucket: Target bucket name.
            object_key: Object key (path) in the bucket.
            expires_in: URL expiration time in seconds.
            filename: Optional filename for Content-Disposition header.

        Returns:
            Presigned URL for GET request.

        Raises:
            StorageError: If URL generation fails.
        """
        ...

    def delete_object(self, *, bucket: str, object_key: str) -> None:
        """Delete an object from storage.

        Args:
            bucket: Target bucket name.
            object_key: Object key (path) to delete.

        Raises:
            StorageError: If the operation fails.
        """
        ...
