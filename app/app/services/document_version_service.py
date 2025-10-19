from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.app.services.base import BaseService
from app.domain.repositories import DocumentVersionRepository
from app.infra.db.models import Document, DocumentVersion


@dataclass(frozen=True)
class DocumentSnapshot:
    document_id: int
    title: str
    metadata: dict[str, Any]
    content: dict[str, Any]


class DocumentVersionNotFoundError(Exception):
    """Raised when the requested document version is missing."""


class DocumentVersionService(BaseService):
    """Application service handling document version lifecycle."""

    def __init__(
        self,
        session: Session,
        repository: DocumentVersionRepository | None = None,
    ):
        super().__init__(session)
        self._repo = repository or DocumentVersionRepository(session)

    def list_versions(
        self, document_id: int, *, page: int, size: int
    ) -> tuple[list[DocumentVersion], int]:
        offset = (page - 1) * size
        items = self._repo.list_by_document(document_id, limit=size, offset=offset)
        total = self._repo.count_by_document(document_id)
        return items, total

    def get_version(self, document_id: int, version_number: int) -> DocumentVersion:
        version = self._repo.get_by_document_and_number(document_id, version_number)
        if version is None:
            raise DocumentVersionNotFoundError("Document version not found")
        return version

    def get_latest_version_number(self, document_id: int) -> int | None:
        return self._repo.get_latest_version_number(document_id)

    def record_snapshot(
        self,
        snapshot: DocumentSnapshot,
        *,
        user_id: str,
        operation: str,
        source_version_number: int | None = None,
        change_summary: dict[str, Any] | None = None,
    ) -> DocumentVersion:
        user = self._ensure_user(user_id)
        next_version = self._next_version_number(snapshot.document_id)
        version = DocumentVersion(
            document_id=snapshot.document_id,
            version_number=next_version,
            operation=operation,
            source_version_number=source_version_number,
            snapshot_title=snapshot.title,
            snapshot_metadata=dict(snapshot.metadata),
            snapshot_content=dict(snapshot.content),
            change_summary=dict(change_summary) if change_summary else None,
            created_by=user,
        )
        self._repo.create(version)
        return version

    def build_snapshot_from_document(self, document: Document) -> DocumentSnapshot:
        return DocumentSnapshot(
            document_id=document.id,
            title=document.title,
            metadata=dict(document.metadata_),
            content=dict(document.content),
        )

    def diff_versions(
        self,
        base_version: DocumentVersion,
        compare_version: DocumentVersion,
    ) -> dict[str, Any]:
        return self.diff_snapshots(
            self.snapshot_from_version(base_version),
            self.snapshot_from_version(compare_version),
        )

    def diff_version_against_document(
        self, version: DocumentVersion, document: Document
    ) -> dict[str, Any]:
        return self.diff_snapshots(
            self.snapshot_from_version(version),
            self.build_snapshot_from_document(document),
        )

    def snapshot_from_version(self, version: DocumentVersion) -> DocumentSnapshot:
        return DocumentSnapshot(
            document_id=version.document_id,
            title=version.snapshot_title,
            metadata=dict(version.snapshot_metadata or {}),
            content=dict(version.snapshot_content or {}),
        )

    def diff_snapshots(
        self, base: DocumentSnapshot, compare: DocumentSnapshot
    ) -> dict[str, Any]:
        diff: dict[str, Any] = {}

        if base.title != compare.title:
            diff["title"] = {"from": base.title, "to": compare.title}

        metadata_diff = self._diff_mapping(base.metadata, compare.metadata)
        if metadata_diff:
            diff["metadata"] = metadata_diff

        content_diff = self._diff_mapping(base.content, compare.content)
        if content_diff:
            diff["content"] = content_diff

        return diff

    def _diff_mapping(
        self, original: dict[str, Any], updated: dict[str, Any]
    ) -> dict[str, Any]:
        added: dict[str, Any] = {}
        removed: list[str] = []
        changed: dict[str, Any] = {}

        for key, value in updated.items():
            if key not in original:
                added[key] = value
            else:
                original_value = original[key]
                if original_value != value:
                    changed[key] = {"from": original_value, "to": value}

        for key in original.keys():
            if key not in updated:
                removed.append(key)

        result: dict[str, Any] = {}
        if added:
            result["added"] = added
        if removed:
            result["removed"] = removed
        if changed:
            result["changed"] = changed
        return result

    def _next_version_number(self, document_id: int) -> int:
        latest = self._repo.get_latest_version_number(document_id) or 0
        pending_numbers = [
            obj.version_number
            for obj in self.session.new
            if isinstance(obj, DocumentVersion) and obj.document_id == document_id
        ]
        if pending_numbers:
            latest = max(latest, max(pending_numbers))
        return latest + 1
