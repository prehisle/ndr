from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.app.services.base import BaseService
from app.domain.repositories import NodeRepository, RelationshipRepository
from app.domain.repositories.node_repository import LtreeNotAvailableError
from app.infra.db.models import Document, Node


class NodeNotFoundError(Exception):
    """Raised when the target node does not exist or is soft-deleted."""


class ParentNodeNotFoundError(Exception):
    """Raised when the specified parent path cannot be located."""


class NodeConflictError(Exception):
    """Raised when creating or updating a node violates a uniqueness constraint."""

    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


class InvalidNodeOperationError(Exception):
    """Raised when a requested node operation is invalid (e.g., cyclic move)."""


@dataclass(frozen=True)
class NodeCreateData:
    name: str
    slug: str
    parent_path: Optional[str]


@dataclass(frozen=True)
class NodeUpdateData:
    name: Optional[str] = None
    slug: Optional[str] = None
    parent_path: Optional[str] = None
    parent_path_set: bool = False


class NodeService(BaseService):
    """Application service orchestrating node-related use cases."""

    def __init__(
        self,
        session: Session,
        repository: NodeRepository | None = None,
        relationship_repository: RelationshipRepository | None = None,
    ):
        super().__init__(session)
        self._repo = repository or NodeRepository(session)
        self._relationships = relationship_repository or RelationshipRepository(session)

    def get_node(self, node_id: int, *, include_deleted: bool = False) -> Node:
        node = self._repo.get(node_id)
        if not node or (node.deleted_at is not None and not include_deleted):
            raise NodeNotFoundError("Node not found")
        return node

    def create_node(self, data: NodeCreateData, *, user_id: str) -> Node:
        user = self._ensure_user(user_id)
        parent_path = data.parent_path or None
        path = data.slug if not parent_path else f"{parent_path}.{data.slug}"

        if self._repo.has_active_path(path):
            raise NodeConflictError("path", "Node path already exists")

        if self._repo.has_active_name(parent_path, data.name):
            raise NodeConflictError(
                "name", "Node name already exists under the same parent"
            )

        node = Node(
            name=data.name,
            slug=data.slug,
            parent_path=parent_path,
            path=path,
            created_by=user,
            updated_by=user,
        )
        self.session.add(node)
        self._commit()
        self.session.refresh(node)
        return node

    def update_node(self, node_id: int, data: NodeUpdateData, *, user_id: str) -> Node:
        user = self._ensure_user(user_id)
        node = self._repo.get(node_id)
        if not node or node.deleted_at is not None:
            raise NodeNotFoundError("Node not found")

        try:
            self._repo.require_ltree()
        except LtreeNotAvailableError as exc:  # pragma: no cover - defensive guard
            raise exc

        parent_node = None
        target_parent_path = node.parent_path
        if data.parent_path_set:
            if data.parent_path:
                parent_node = self._repo.get_active_by_path(data.parent_path)
                if not parent_node:
                    raise ParentNodeNotFoundError("Parent node not found")
                if parent_node.id == node.id:
                    raise InvalidNodeOperationError(
                        "Cannot set a node as its own parent"
                    )
                if parent_node.path.startswith(f"{node.path}."):
                    raise InvalidNodeOperationError(
                        "Cannot move a node under its own subtree"
                    )
                target_parent_path = parent_node.path
            else:
                target_parent_path = None

        lock_ids = [node.id]
        if parent_node:
            lock_ids.append(parent_node.id)
        self._repo.lock_nodes(lock_ids)

        new_name = data.name if data.name is not None else node.name
        new_slug = data.slug if data.slug is not None else node.slug
        new_parent_path = target_parent_path

        if self._repo.has_active_name(new_parent_path, new_name, exclude_id=node.id):
            raise NodeConflictError(
                "name", "Node name already exists under the same parent"
            )

        new_path = (
            new_slug if new_parent_path is None else f"{new_parent_path}.{new_slug}"
        )

        if self._repo.has_active_path(new_path, exclude_id=node.id):
            raise NodeConflictError("path", "Node path already exists")

        path_changed = new_path != node.path

        if data.name is not None:
            node.name = new_name
        if data.slug is not None:
            node.slug = new_slug
        if data.parent_path_set:
            node.parent_path = new_parent_path

        if path_changed:
            old_path = node.path
            descendants = self._repo.fetch_descendants(old_path, exclude_id=node.id)
            node.path = new_path
            prefix = f"{old_path}."
            for descendant in descendants:
                if not descendant.path.startswith(prefix):
                    continue
                suffix = descendant.path[len(prefix) :]
                descendant.path = f"{new_path}.{suffix}"
                if "." in descendant.path:
                    descendant.parent_path = descendant.path.rsplit(".", 1)[0]
                else:
                    descendant.parent_path = None
                descendant.updated_by = user

        node.updated_by = user
        self._commit()
        self.session.refresh(node)
        return node

    def soft_delete_node(self, node_id: int, *, user_id: str) -> None:
        user = self._ensure_user(user_id)
        node = self._repo.get(node_id)
        if not node or node.deleted_at is not None:
            raise NodeNotFoundError("Node not found or already deleted")
        node.deleted_at = datetime.now(timezone.utc)
        node.updated_by = user
        self._commit()

    def list_nodes(
        self, *, page: int, size: int, include_deleted: bool = False
    ) -> tuple[list[Node], int]:
        return self._repo.paginate_nodes(page, size, include_deleted)

    def list_children(self, node_id: int, *, depth: int) -> list[Node]:
        node = self._repo.get(node_id)
        if not node:
            raise NodeNotFoundError("Node not found")
        self._repo.require_ltree()
        return list(self._repo.fetch_children(node.path, depth))

    def restore_node(self, node_id: int, *, user_id: str) -> Node:
        user = self._ensure_user(user_id)
        node = self._repo.get(node_id)
        if not node:
            raise NodeNotFoundError("Node not found")
        if node.deleted_at is None:
            return node

        # Ensure path/name constraints still valid before restoring
        if self._repo.has_active_path(node.path, exclude_id=node.id):
            raise NodeConflictError("path", "Node path already exists")
        if self._repo.has_active_name(node.parent_path, node.name, exclude_id=node.id):
            raise NodeConflictError(
                "name", "Node name already exists under the same parent"
            )

        node.deleted_at = None
        node.updated_by = user
        node.updated_at = datetime.now(timezone.utc)
        self._commit()
        self.session.refresh(node)
        return node

    def get_subtree_documents(
        self,
        node_id: int,
        *,
        include_deleted_nodes: bool = False,
        include_deleted_documents: bool = False,
    ) -> list[Document]:
        node = self._repo.get(node_id)
        if not node or (node.deleted_at is not None and not include_deleted_nodes):
            raise NodeNotFoundError("Node not found")
        self._repo.require_ltree()

        subtree_nodes = self._repo.fetch_subtree(
            node.path, include_deleted=include_deleted_nodes
        )
        node_ids = {n.id for n in subtree_nodes}
        node_ids.add(node.id)
        documents = self._relationships.list_documents_for_nodes(
            sorted(node_ids),
            include_deleted_relations=include_deleted_nodes,
            include_deleted_documents=include_deleted_documents,
        )
        return documents
