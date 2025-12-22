"""Asset service for file upload and management operations.

This module provides the application service layer for managing file assets,
including multipart upload orchestration, metadata management, and download URL generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy.orm import Session

from app.app.services.base import BaseService
from app.common.config import Settings, get_settings
from app.domain.repositories.asset_repository import AssetRepository
from app.infra.db.models import Asset
from app.infra.storage.client import CompletedPart, StorageClient
from app.infra.storage.s3_client import S3StorageClient

# Maximum number of part URLs that can be requested at once
MAX_PART_URLS_PER_REQUEST = 1000
# Maximum part number allowed by S3
MAX_PART_NUMBER = 10000


class AssetNotFoundError(Exception):
    """Raised when the requested asset does not exist or is deleted."""


class InvalidAssetOperationError(Exception):
    """Raised when the asset state does not allow the requested operation."""


class StorageBackendNotConfiguredError(Exception):
    """Raised when the storage backend is not properly configured."""


@dataclass(frozen=True, slots=True)
class AssetMultipartInitData:
    """Input data for initiating a multipart upload."""

    filename: str
    content_type: str | None
    size_bytes: int


@dataclass(frozen=True, slots=True)
class AssetMultipartInitResult:
    """Result of initiating a multipart upload."""

    asset: Asset
    upload_id: str
    part_size_bytes: int
    expires_in: int


@dataclass(frozen=True, slots=True)
class AssetPartUrl:
    """Presigned URL for uploading a part."""

    part_number: int
    url: str


@dataclass(frozen=True, slots=True)
class AssetDownloadUrl:
    """Presigned URL for downloading an asset."""

    url: str
    expires_in: int


def _sanitize_filename(filename: str) -> str:
    """Sanitize filename by removing path separators."""
    cleaned = filename.strip().replace("\\", "_").replace("/", "_")
    return cleaned or "file"


class AssetService(BaseService):
    """Application service for file asset lifecycle management.

    Handles multipart upload orchestration, metadata operations,
    and presigned URL generation for downloads.
    """

    def __init__(
        self,
        session: Session,
        *,
        repository: AssetRepository | None = None,
        storage_client: StorageClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(session)
        self._repo = repository or AssetRepository(session)
        self._settings = settings or get_settings()
        self._storage = storage_client or self._build_storage_client(self._settings)

    @staticmethod
    def _build_storage_client(settings: Settings) -> StorageClient:
        """Build the appropriate storage client based on configuration."""
        backend = (settings.STORAGE_BACKEND or "").strip().lower()
        if backend != "s3":
            raise StorageBackendNotConfiguredError(
                f"Unsupported storage backend: {backend}. Only 's3' is supported."
            )
        if not settings.S3_BUCKET:
            raise StorageBackendNotConfiguredError("S3_BUCKET is required")
        if not settings.S3_ACCESS_KEY_ID or not settings.S3_SECRET_ACCESS_KEY:
            raise StorageBackendNotConfiguredError(
                "S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY are required"
            )
        return S3StorageClient(settings=settings)

    def create_multipart_upload(
        self,
        data: AssetMultipartInitData,
        *,
        user_id: str,
    ) -> AssetMultipartInitResult:
        """Create an asset and initialize a multipart upload session.

        Args:
            data: Upload initialization parameters.
            user_id: ID of the user initiating the upload.

        Returns:
            AssetMultipartInitResult with asset, upload_id, and configuration.

        Raises:
            MissingUserError: If user_id is not provided.
            InvalidAssetOperationError: If parameters are invalid.
        """
        user = self._ensure_user(user_id)

        if data.size_bytes <= 0:
            raise InvalidAssetOperationError("size_bytes must be positive")
        if data.size_bytes > self._settings.STORAGE_MAX_UPLOAD_BYTES:
            raise InvalidAssetOperationError(
                f"File size exceeds maximum allowed ({self._settings.STORAGE_MAX_UPLOAD_BYTES} bytes)"
            )

        filename = _sanitize_filename(data.filename)
        content_type = data.content_type.strip() if data.content_type else None

        # Create asset record with placeholder object_key
        asset = Asset(
            filename=filename,
            content_type=content_type,
            size_bytes=int(data.size_bytes),
            status="UPLOADING",
            storage_backend="s3",
            bucket=self._settings.S3_BUCKET,
            object_key="__pending__",
            metadata_={},
            created_by=user,
            updated_by=user,
        )
        self.session.add(asset)
        self.session.flush()

        # Generate object key using asset ID for uniqueness
        prefix = (self._settings.S3_PREFIX or "assets/").lstrip("/")
        object_key = f"{prefix}{asset.id}/{filename}"
        asset.object_key = object_key

        # Initialize multipart upload in storage backend
        upload = self._storage.init_multipart_upload(
            bucket=asset.bucket,
            object_key=asset.object_key,
            content_type=asset.content_type,
            metadata={"asset_id": str(asset.id)},
        )

        # Store upload session info in metadata
        part_size = int(self._settings.STORAGE_PART_SIZE_BYTES)
        asset.metadata_ = {
            **dict(asset.metadata_ or {}),
            "multipart": {
                "upload_id": upload.upload_id,
                "part_size_bytes": part_size,
                "initiated_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        self._commit()
        self.session.refresh(asset)

        return AssetMultipartInitResult(
            asset=asset,
            upload_id=upload.upload_id,
            part_size_bytes=part_size,
            expires_in=int(self._settings.STORAGE_PRESIGN_EXPIRES_SECONDS),
        )

    def get_asset(self, asset_id: int, *, include_deleted: bool = False) -> Asset:
        """Get an asset by ID.

        Args:
            asset_id: The asset's primary key.
            include_deleted: Whether to include soft-deleted assets.

        Returns:
            The Asset entity.

        Raises:
            AssetNotFoundError: If the asset doesn't exist or is deleted.
        """
        asset = self._repo.get(asset_id)
        if not asset or (asset.deleted_at is not None and not include_deleted):
            raise AssetNotFoundError("Asset not found")
        return asset

    def list_assets(
        self,
        *,
        page: int,
        size: int,
        include_deleted: bool = False,
        search_query: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Asset], int]:
        """List assets with pagination and optional filters.

        Args:
            page: Page number (1-based).
            size: Number of items per page.
            include_deleted: Include soft-deleted assets.
            search_query: Optional filename search pattern.
            status: Optional status filter.

        Returns:
            Tuple of (list of assets, total count).
        """
        return self._repo.paginate_assets(
            page=page,
            size=size,
            include_deleted=include_deleted,
            search_query=search_query,
            status=status,
        )

    def presign_upload_parts(
        self,
        asset_id: int,
        part_numbers: Sequence[int],
    ) -> tuple[str, list[AssetPartUrl]]:
        """Generate presigned URLs for uploading parts.

        Args:
            asset_id: The asset's primary key.
            part_numbers: List of part numbers to presign (max 1000 per request).

        Returns:
            Tuple of (upload_id, list of presigned part URLs).

        Raises:
            AssetNotFoundError: If the asset doesn't exist.
            InvalidAssetOperationError: If the asset is not in UPLOADING state.
        """
        # Validate part_numbers to prevent DoS
        if len(part_numbers) > MAX_PART_URLS_PER_REQUEST:
            raise InvalidAssetOperationError(
                f"Cannot request more than {MAX_PART_URLS_PER_REQUEST} part URLs at once"
            )

        # Deduplicate and validate
        unique_parts = list(dict.fromkeys(part_numbers))
        for pn in unique_parts:
            if pn <= 0 or pn > MAX_PART_NUMBER:
                raise InvalidAssetOperationError(
                    f"part_number must be between 1 and {MAX_PART_NUMBER}"
                )

        asset = self.get_asset(asset_id)
        if asset.status != "UPLOADING":
            raise InvalidAssetOperationError("Asset is not in UPLOADING state")

        meta = dict(asset.metadata_ or {})
        multipart_raw = meta.get("multipart")
        multipart: dict[str, Any] = (
            multipart_raw if isinstance(multipart_raw, dict) else {}
        )
        upload_id = multipart.get("upload_id")
        if not upload_id:
            raise InvalidAssetOperationError(
                "Missing multipart upload_id in asset metadata"
            )

        expires_in = int(self._settings.STORAGE_PRESIGN_EXPIRES_SECONDS)
        urls: list[AssetPartUrl] = []

        for part_number in unique_parts:
            url = self._storage.presign_upload_part(
                bucket=asset.bucket,
                object_key=asset.object_key,
                upload_id=str(upload_id),
                part_number=int(part_number),
                expires_in=expires_in,
            )
            urls.append(AssetPartUrl(part_number=int(part_number), url=url))

        return str(upload_id), urls

    def complete_multipart_upload(
        self,
        asset_id: int,
        *,
        parts: Sequence[CompletedPart],
        user_id: str,
    ) -> Asset:
        """Complete a multipart upload.

        Args:
            asset_id: The asset's primary key.
            parts: List of completed parts with their ETags.
            user_id: ID of the user completing the upload.

        Returns:
            The updated Asset with READY status.

        Raises:
            AssetNotFoundError: If the asset doesn't exist.
            InvalidAssetOperationError: If the asset is not in UPLOADING state.
        """
        user = self._ensure_user(user_id)
        asset = self.get_asset(asset_id)

        if asset.status != "UPLOADING":
            raise InvalidAssetOperationError("Asset is not in UPLOADING state")

        meta = dict(asset.metadata_ or {})
        multipart_raw = meta.get("multipart")
        multipart: dict[str, Any] = (
            multipart_raw if isinstance(multipart_raw, dict) else {}
        )
        upload_id = multipart.get("upload_id")
        if not upload_id:
            raise InvalidAssetOperationError(
                "Missing multipart upload_id in asset metadata"
            )

        if not parts:
            raise InvalidAssetOperationError("parts list cannot be empty")

        # Complete the upload in storage backend
        self._storage.complete_multipart_upload(
            bucket=asset.bucket,
            object_key=asset.object_key,
            upload_id=str(upload_id),
            parts=parts,
        )

        # Get actual object metadata from storage
        head = self._storage.head_object(
            bucket=asset.bucket, object_key=asset.object_key
        )

        # Verify file size doesn't exceed limit
        if (
            head.size_bytes
            and head.size_bytes > self._settings.STORAGE_MAX_UPLOAD_BYTES
        ):
            # Mark as failed and attempt cleanup
            asset.status = "FAILED"
            asset.metadata_ = {
                **dict(asset.metadata_ or {}),
                "error": f"File size {head.size_bytes} exceeds limit {self._settings.STORAGE_MAX_UPLOAD_BYTES}",
            }
            asset.updated_by = user
            self._commit()
            # Attempt to delete the oversized object
            try:
                self._storage.delete_object(
                    bucket=asset.bucket, object_key=asset.object_key
                )
            except Exception:
                pass  # Best effort cleanup
            raise InvalidAssetOperationError(
                f"Uploaded file size ({head.size_bytes} bytes) exceeds maximum allowed ({self._settings.STORAGE_MAX_UPLOAD_BYTES} bytes)"
            )

        # Update asset with final metadata
        asset.status = "READY"
        asset.etag = head.etag
        if head.size_bytes:
            asset.size_bytes = int(head.size_bytes)
        if head.content_type and not asset.content_type:
            asset.content_type = head.content_type
        asset.updated_by = user

        self._commit()
        self.session.refresh(asset)
        return asset

    def presign_download_url(self, asset_id: int) -> AssetDownloadUrl:
        """Generate a presigned URL for downloading an asset.

        Args:
            asset_id: The asset's primary key.

        Returns:
            AssetDownloadUrl with the presigned URL and expiration.

        Raises:
            AssetNotFoundError: If the asset doesn't exist.
            InvalidAssetOperationError: If the asset is not in READY state.
        """
        asset = self.get_asset(asset_id)
        if asset.status != "READY":
            raise InvalidAssetOperationError("Asset is not ready for download")

        expires_in = int(self._settings.STORAGE_PRESIGN_EXPIRES_SECONDS)
        url = self._storage.presign_download(
            bucket=asset.bucket,
            object_key=asset.object_key,
            expires_in=expires_in,
            filename=asset.filename,
        )

        return AssetDownloadUrl(url=url, expires_in=expires_in)

    def soft_delete_asset(self, asset_id: int, *, user_id: str) -> None:
        """Soft-delete an asset.

        Args:
            asset_id: The asset's primary key.
            user_id: ID of the user deleting the asset.

        Raises:
            AssetNotFoundError: If the asset doesn't exist or is already deleted.
        """
        user = self._ensure_user(user_id)
        asset = self._repo.get(asset_id)

        if not asset or asset.deleted_at is not None:
            raise AssetNotFoundError("Asset not found or already deleted")

        asset.deleted_at = datetime.now(timezone.utc)
        asset.status = "DELETED"
        asset.updated_by = user

        self._commit()

    def abort_multipart_upload(self, asset_id: int, *, user_id: str) -> None:
        """Abort a multipart upload and mark the asset as ABORTED.

        Args:
            asset_id: The asset's primary key.
            user_id: ID of the user aborting the upload.

        Raises:
            AssetNotFoundError: If the asset doesn't exist.
            InvalidAssetOperationError: If the asset is not in UPLOADING state.
        """
        user = self._ensure_user(user_id)
        asset = self.get_asset(asset_id)

        if asset.status != "UPLOADING":
            raise InvalidAssetOperationError("Asset is not in UPLOADING state")

        meta = dict(asset.metadata_ or {})
        multipart_raw = meta.get("multipart")
        multipart: dict[str, Any] = (
            multipart_raw if isinstance(multipart_raw, dict) else {}
        )
        upload_id = multipart.get("upload_id")

        if upload_id:
            try:
                self._storage.abort_multipart_upload(
                    bucket=asset.bucket,
                    object_key=asset.object_key,
                    upload_id=str(upload_id),
                )
            except Exception:
                pass  # Best effort - upload may already be aborted or expired

        asset.status = "ABORTED"
        asset.updated_by = user
        asset.metadata_ = {
            **dict(asset.metadata_ or {}),
            "aborted_at": datetime.now(timezone.utc).isoformat(),
        }

        self._commit()
