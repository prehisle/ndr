"""Pydantic schemas for asset API endpoints.

This module defines request and response models for the asset-related
REST API endpoints, including multipart upload and node binding operations.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AssetMultipartInit(BaseModel):
    """Request body for initiating a multipart upload."""

    filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = None
    size_bytes: int = Field(ge=1)


class AssetPartUrl(BaseModel):
    """Presigned URL for a single upload part."""

    part_number: int
    url: str


class AssetPartUrlsRequest(BaseModel):
    """Request body for getting presigned part URLs."""

    part_numbers: list[int] = Field(default_factory=list)


class AssetCompletedPart(BaseModel):
    """Information about a completed upload part."""

    part_number: int = Field(ge=1)
    etag: str = Field(min_length=1)


class AssetMultipartComplete(BaseModel):
    """Request body for completing a multipart upload."""

    parts: list[AssetCompletedPart] = Field(default_factory=list, min_length=1)


class AssetOut(BaseModel):
    """Response model for asset data."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str | None = None
    size_bytes: int
    status: str
    bucket: str
    object_key: str
    etag: str | None = None
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class AssetMultipartInitOut(BaseModel):
    """Response model for multipart upload initialization."""

    asset: AssetOut
    upload_id: str
    part_size_bytes: int
    expires_in: int


class AssetPartUrlsOut(BaseModel):
    """Response model for presigned part URLs."""

    upload_id: str
    urls: list[AssetPartUrl]
    expires_in: int


class AssetDownloadUrlOut(BaseModel):
    """Response model for download URL."""

    url: str
    expires_in: int


class AssetsPage(BaseModel):
    """Paginated list of assets."""

    page: int
    size: int
    total: int
    items: list[AssetOut]


class AssetBatchBind(BaseModel):
    """Request body for batch binding an asset to nodes."""

    node_ids: list[int] = Field(default_factory=list)


class AssetBindingOut(BaseModel):
    """Response model for an asset-node binding."""

    node_id: int
    node_name: str
    node_path: str
    created_at: datetime


class AssetBindingStatus(BaseModel):
    """Summary of an asset's bindings."""

    total_bindings: int
    node_ids: list[int]
