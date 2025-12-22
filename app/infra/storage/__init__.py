"""Object storage abstraction layer.

This module provides a protocol-based abstraction for object storage backends,
enabling support for S3, MinIO, and other S3-compatible services.
"""

from .client import (
    CompletedPart,
    MultipartUpload,
    ObjectHead,
    StorageClient,
    StorageError,
)

__all__ = [
    "CompletedPart",
    "MultipartUpload",
    "ObjectHead",
    "StorageClient",
    "StorageError",
]
