"""Mock storage client for testing asset operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.infra.storage.client import CompletedPart, MultipartUpload, ObjectHead


@dataclass
class MockStorageClient:
    """In-memory mock of StorageClient for testing."""

    uploads: dict[str, dict[str, Any]] = field(default_factory=dict)
    objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    _upload_counter: int = field(default=0)

    def init_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> MultipartUpload:
        self._upload_counter += 1
        upload_id = f"mock-upload-{self._upload_counter}"
        self.uploads[upload_id] = {
            "bucket": bucket,
            "object_key": object_key,
            "content_type": content_type,
            "metadata": metadata or {},
            "parts": {},
            "completed": False,
            "aborted": False,
        }
        return MultipartUpload(
            upload_id=upload_id, bucket=bucket, object_key=object_key
        )

    def presign_upload_part(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        part_number: int,
        expires_in: int = 3600,
    ) -> str:
        return f"https://mock-s3/{bucket}/{object_key}?uploadId={upload_id}&partNumber={part_number}"

    def complete_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        parts: list[CompletedPart],
    ) -> None:
        if upload_id not in self.uploads:
            raise ValueError(f"Upload {upload_id} not found")

        upload = self.uploads[upload_id]
        upload["completed"] = True
        upload["parts"] = {p.part_number: p.etag for p in parts}

        total_size = sum(1024 * 1024 for _ in parts)  # Mock 1MB per part
        self.objects[f"{bucket}/{object_key}"] = {
            "bucket": bucket,
            "object_key": object_key,
            "content_type": upload["content_type"],
            "size_bytes": total_size,
            "etag": f"mock-etag-{upload_id}",
        }

    def abort_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
    ) -> None:
        if upload_id in self.uploads:
            self.uploads[upload_id]["aborted"] = True

    def head_object(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> ObjectHead:
        key = f"{bucket}/{object_key}"
        if key not in self.objects:
            return ObjectHead(size_bytes=None, etag=None, content_type=None)

        obj = self.objects[key]
        return ObjectHead(
            size_bytes=obj.get("size_bytes"),
            etag=obj.get("etag"),
            content_type=obj.get("content_type"),
        )

    def presign_download(
        self,
        *,
        bucket: str,
        object_key: str,
        expires_in: int = 3600,
        filename: str | None = None,
    ) -> str:
        return f"https://mock-s3/{bucket}/{object_key}?download=true"

    def delete_object(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> None:
        key = f"{bucket}/{object_key}"
        self.objects.pop(key, None)

    def set_object_size(self, bucket: str, object_key: str, size_bytes: int) -> None:
        """Test helper to set the size of an object after upload."""
        key = f"{bucket}/{object_key}"
        if key in self.objects:
            self.objects[key]["size_bytes"] = size_bytes
        else:
            self.objects[key] = {
                "bucket": bucket,
                "object_key": object_key,
                "size_bytes": size_bytes,
                "etag": "mock-etag",
                "content_type": None,
            }
