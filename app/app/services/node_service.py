from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.app.services.base import BaseService
from app.domain import COUNTED_RELATION_TYPE
from app.domain.repositories import NodeRepository, RelationshipRepository
from app.domain.repositories.document_filters import MetadataFilters
from app.domain.repositories.node_repository import LtreeNotAvailableError
from app.infra.db.models import Document, Node, NodeDocument


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
    type: Optional[str] = None


@dataclass(frozen=True)
class NodeUpdateData:
    name: Optional[str] = None
    slug: Optional[str] = None
    parent_path: Optional[str] = None
    parent_path_set: bool = False
    type: Optional[str] = None


@dataclass(frozen=True)
class NodeReorderData:
    parent_id: Optional[int]
    ordered_ids: tuple[int, ...]


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

    def get_node_by_path(self, path: str, *, include_deleted: bool = False) -> Node:
        """通过路径获取节点。

        Args:
            path: 节点路径，如 "course.chapter.section"
            include_deleted: 是否包含已删除的节点

        Returns:
            匹配的节点

        Raises:
            NodeNotFoundError: 节点不存在或已被删除
        """
        if include_deleted:
            # 如果需要包含已删除节点，使用通用查询
            # 优先返回活跃节点（deleted_at IS NULL），然后按删除时间倒序
            from sqlalchemy import select

            from app.infra.db.models import Node as NodeModel

            stmt = (
                select(NodeModel)
                .where(NodeModel.path == path)
                .order_by(
                    NodeModel.deleted_at.is_(None).desc(), NodeModel.deleted_at.desc()
                )
            )
            node = self.session.execute(stmt).scalars().first()
        else:
            node = self._repo.get_active_by_path(path)

        if not node:
            raise NodeNotFoundError(f"Node not found: {path}")
        return node

    def create_node(self, data: NodeCreateData, *, user_id: str) -> Node:
        user = self._ensure_user(user_id)
        # 兜底校验，防止绕过 API 层的非法 slug 写入
        if not re.fullmatch(r"[a-z0-9_-]{1,255}", data.slug):
            raise InvalidNodeOperationError(
                "slug 仅允许小写字母、数字、下划线与短横线，长度 1..255"
            )
        parent_node = None
        parent_path = data.parent_path or None
        if parent_path:
            parent_node = self._repo.get_active_by_path(parent_path)
            if not parent_node:
                raise ParentNodeNotFoundError("Parent node not found")
            parent_path = parent_node.path

        path = data.slug if not parent_path else f"{parent_path}.{data.slug}"
        parent_id = parent_node.id if parent_node else None
        position = self._repo.next_position(parent_id)

        if self._repo.has_active_path(path):
            raise NodeConflictError("path", "Node path already exists")

        if self._repo.has_active_name(parent_path, data.name):
            raise NodeConflictError(
                "name", "Node name already exists under the same parent"
            )

        node = Node(
            name=data.name,
            slug=data.slug,
            parent_id=parent_id,
            parent_path=parent_path,
            path=path,
            position=position,
            type=data.type,
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

        # 可选的 slug 变更同样进行兜底校验
        if data.slug is not None and not re.fullmatch(r"[a-z0-9_-]{1,255}", data.slug):
            raise InvalidNodeOperationError(
                "slug 仅允许小写字母、数字、下划线与短横线，长度 1..255"
            )

        parent_node = None
        target_parent_path = node.parent_path
        target_parent_id = node.parent_id
        original_parent_id = node.parent_id
        original_parent_path = node.parent_path
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
                target_parent_id = parent_node.id
            else:
                target_parent_path = None
                target_parent_id = None

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
        if data.type is not None:
            node.type = data.type
        if data.parent_path_set:
            node.parent_id = target_parent_id
            node.parent_path = new_parent_path
            if target_parent_id != original_parent_id:
                node.position = self._repo.next_position(target_parent_id)
                # 迁移计数：把整棵子树的 output 绑定总数从旧父链挪到新父链
                self._migrate_subtree_counts_on_move(
                    node.path, original_parent_path, new_parent_path
                )

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
            # Ensure descendant parent IDs follow the updated paths
            updated_nodes = [node, *descendants]
            path_to_id = {n.path: n.id for n in updated_nodes}
            for descendant in descendants:
                if descendant.parent_path:
                    descendant.parent_id = path_to_id.get(descendant.parent_path)
                else:
                    descendant.parent_id = None

        node.updated_by = user
        if data.parent_path_set and target_parent_id != original_parent_id:
            self._repo.normalize_positions(original_parent_id)
            self._repo.normalize_positions(target_parent_id)
        self._commit()
        self.session.refresh(node)
        return node

    def _migrate_subtree_counts_on_move(
        self,
        subtree_root_path: str,
        old_parent_path: Optional[str],
        new_parent_path: Optional[str],
    ) -> None:
        """节点移动时迁移子树的 output 绑定计数到新祖先链。

        Args:
            subtree_root_path: 被移动子树根节点的路径
            old_parent_path: 原父节点路径（根节点为 None）
            new_parent_path: 新父节点路径（根节点为 None）
        """
        from sqlalchemy import func, select

        # 获取子树所有节点 ID（包括根节点和所有后代）
        subtree_nodes = self._repo.fetch_subtree(
            subtree_root_path, include_deleted=False
        )
        subtree_node_ids = [n.id for n in subtree_nodes]
        if not subtree_node_ids:
            return

        # 统计子树中 output 类型的活跃绑定总数
        counted_stmt = (
            select(func.count())
            .select_from(NodeDocument)
            .join(Document, Document.id == NodeDocument.document_id)
            .where(NodeDocument.deleted_at.is_(None))
            .where(NodeDocument.relation_type == COUNTED_RELATION_TYPE)
            .where(NodeDocument.node_id.in_(subtree_node_ids))
            .where(Document.deleted_at.is_(None))
        )
        subtree_binding_count = self.session.execute(counted_stmt).scalar_one()

        if not subtree_binding_count:
            return

        # 计算旧父链和新父链的祖先 ID
        old_external_ancestor_ids = (
            self._repo.get_ancestor_ids(old_parent_path) if old_parent_path else []
        )
        new_external_ancestor_ids = (
            self._repo.get_ancestor_ids(new_parent_path) if new_parent_path else []
        )

        # 从旧祖先链减去计数
        if old_external_ancestor_ids:
            self._repo.update_subtree_counts(
                old_external_ancestor_ids, -subtree_binding_count
            )

        # 向新祖先链加上计数
        if new_external_ancestor_ids:
            self._repo.update_subtree_counts(
                new_external_ancestor_ids, +subtree_binding_count
            )

    def soft_delete_node(self, node_id: int, *, user_id: str) -> None:
        user = self._ensure_user(user_id)
        node = self._repo.get(node_id)
        if not node or node.deleted_at is not None:
            raise NodeNotFoundError("Node not found or already deleted")

        # 删除节点前，减去该节点直接绑定的 output 文档对祖先链的贡献
        self._decrement_ancestor_counts_for_node(node)

        parent_id = node.parent_id
        node.deleted_at = datetime.now(timezone.utc)
        node.updated_by = user
        self._repo.normalize_positions(parent_id)
        self._commit()

    def _decrement_ancestor_counts_for_node(self, node: Node) -> None:
        """减去节点直接绑定的 output 文档对祖先链的贡献。"""
        from sqlalchemy import func, select

        direct_count_stmt = (
            select(func.count())
            .select_from(NodeDocument)
            .join(Document, Document.id == NodeDocument.document_id)
            .where(NodeDocument.deleted_at.is_(None))
            .where(NodeDocument.relation_type == COUNTED_RELATION_TYPE)
            .where(NodeDocument.node_id == node.id)
            .where(Document.deleted_at.is_(None))
        )
        direct_output_count = self.session.execute(direct_count_stmt).scalar_one()

        if direct_output_count and node.parent_path:
            ancestor_ids = self._repo.get_ancestor_ids(node.parent_path)
            self._repo.update_subtree_counts(ancestor_ids, -direct_output_count)

    def purge_node(self, node_id: int, *, user_id: str) -> None:
        self._ensure_user(user_id)
        node = self._repo.get(node_id)
        if not node:
            raise NodeNotFoundError("Node not found")
        if node.deleted_at is None:
            raise InvalidNodeOperationError(
                "Node must be soft-deleted before permanent removal"
            )

        subtree = list(self._repo.fetch_subtree(node.path, include_deleted=True))
        nodes_to_remove = {node.id}
        node_map = {node.id: node}
        for descendant in subtree:
            nodes_to_remove.add(descendant.id)
            node_map.setdefault(descendant.id, descendant)

        if nodes_to_remove:
            self.session.execute(
                delete(NodeDocument).where(NodeDocument.node_id.in_(nodes_to_remove))
            )
            for node_id_to_delete in nodes_to_remove:
                target = node_map.get(node_id_to_delete)
                if target is None:
                    target = self._repo.get(node_id_to_delete)
                if target is not None:
                    self.session.delete(target)

        self._repo.normalize_positions(node.parent_id)
        self._commit()

    def reorder_children(self, data: NodeReorderData, *, user_id: str) -> list[Node]:
        user = self._ensure_user(user_id)

        parent_id = data.parent_id
        if parent_id is not None:
            parent_node = self._repo.get(parent_id)
            if not parent_node or parent_node.deleted_at is not None:
                raise ParentNodeNotFoundError("Parent node not found")

        siblings = list(self._repo.fetch_siblings(parent_id, include_deleted=False))
        if not siblings:
            if data.ordered_ids:
                raise NodeNotFoundError("Node not found")
            return []

        provided_ids = list(data.ordered_ids)
        provided_ids_set = set(provided_ids)
        if len(provided_ids) != len(provided_ids_set):
            raise InvalidNodeOperationError("Duplicate node ids in reorder payload")

        sibling_ids = {node.id for node in siblings}
        missing = provided_ids_set - sibling_ids
        if missing:
            raise NodeNotFoundError("Node not found")

        node_by_id = {node.id: node for node in siblings}
        ordered_nodes = [node_by_id[node_id] for node_id in provided_ids]
        remaining_nodes = [node for node in siblings if node.id not in provided_ids_set]
        sequence = ordered_nodes + remaining_nodes

        lock_ids = [node.id for node in sequence]
        if parent_id is not None:
            lock_ids.append(parent_id)
        self._repo.lock_nodes(lock_ids)

        for index, node in enumerate(sequence):
            if node.position != index:
                node.position = index
                node.updated_by = user

        self._commit()
        return sequence

    def list_nodes(
        self,
        *,
        page: int,
        size: int,
        include_deleted: bool = False,
        node_type: str | None = None,
    ) -> tuple[list[Node], int]:
        return self._repo.paginate_nodes(page, size, include_deleted, node_type)

    def list_children(
        self, node_id: int, *, depth: int, node_type: str | None = None
    ) -> list[Node]:
        node = self._repo.get(node_id)
        if not node:
            raise NodeNotFoundError("Node not found")
        self._repo.require_ltree()
        descendants = list(self._repo.fetch_children(node.path, depth))
        if not descendants:
            return []

        children_map: dict[int, list[Node]] = {}
        for descendant in descendants:
            if descendant.parent_id is None:
                continue
            siblings = children_map.setdefault(descendant.parent_id, [])
            siblings.append(descendant)

        for siblings in children_map.values():
            siblings.sort(key=lambda n: (n.position, n.id))

        ordered: list[Node] = []
        current_level = children_map.get(node.id, [])
        current_depth = 1
        while current_level and current_depth <= depth:
            next_level: list[Node] = []
            for child in current_level:
                if node_type is None or child.type == node_type:
                    ordered.append(child)
                if current_depth < depth:
                    next_level.extend(children_map.get(child.id, []))
            current_level = next_level
            current_depth += 1
        return ordered

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

        # 恢复节点后：补回该节点直接绑定的 output 文档对祖先链的贡献
        self._increment_ancestor_counts_for_node(node)

        # 重算该节点自身的 subtree_doc_count
        self._recalculate_node_subtree_count(node)

        self._repo.normalize_positions(node.parent_id)
        self._commit()
        self.session.refresh(node)
        return node

    def _increment_ancestor_counts_for_node(self, node: Node) -> None:
        """补回节点直接绑定的 output 文档对祖先链的贡献。"""
        from sqlalchemy import func, select

        direct_count_stmt = (
            select(func.count())
            .select_from(NodeDocument)
            .join(Document, Document.id == NodeDocument.document_id)
            .where(NodeDocument.deleted_at.is_(None))
            .where(NodeDocument.relation_type == COUNTED_RELATION_TYPE)
            .where(NodeDocument.node_id == node.id)
            .where(Document.deleted_at.is_(None))
        )
        direct_output_count = self.session.execute(direct_count_stmt).scalar_one()

        if direct_output_count and node.parent_path:
            ancestor_ids = self._repo.get_ancestor_ids(node.parent_path)
            self._repo.update_subtree_counts(ancestor_ids, +direct_output_count)

    def _recalculate_node_subtree_count(self, node: Node) -> None:
        """重算该节点自身的 subtree_doc_count。"""
        from sqlalchemy import func, select

        subtree_nodes = self._repo.fetch_subtree(node.path, include_deleted=False)
        subtree_node_ids = [n.id for n in subtree_nodes]

        if subtree_node_ids:
            subtree_count_stmt = (
                select(func.count())
                .select_from(NodeDocument)
                .join(Document, Document.id == NodeDocument.document_id)
                .where(NodeDocument.deleted_at.is_(None))
                .where(NodeDocument.relation_type == COUNTED_RELATION_TYPE)
                .where(NodeDocument.node_id.in_(subtree_node_ids))
                .where(Document.deleted_at.is_(None))
            )
            node.subtree_doc_count = self.session.execute(
                subtree_count_stmt
            ).scalar_one()
        else:
            node.subtree_doc_count = 0

    def get_subtree_documents(
        self,
        node_id: int,
        *,
        include_deleted_nodes: bool = False,
        include_deleted_documents: bool = False,
        include_descendants: bool = True,
        metadata_filters: MetadataFilters | None = None,
        search_query: str | None = None,
        doc_type: str | None = None,
        doc_ids: Sequence[int] | None = None,
    ) -> list[Document]:
        node = self._repo.get(node_id)
        if not node or (node.deleted_at is not None and not include_deleted_nodes):
            raise NodeNotFoundError("Node not found")

        node_ids: set[int]
        if include_descendants:
            self._repo.require_ltree()
            subtree_nodes = self._repo.fetch_subtree(
                node.path, include_deleted=include_deleted_nodes
            )
            node_ids = {n.id for n in subtree_nodes}
            node_ids.add(node.id)
        else:
            node_ids = {node.id}

        documents = self._relationships.list_documents_for_nodes(
            sorted(node_ids),
            include_deleted_relations=include_deleted_nodes,
            include_deleted_documents=include_deleted_documents,
            metadata_filters=metadata_filters,
            search_query=search_query,
            doc_type=doc_type,
            doc_ids=doc_ids,
        )
        return documents

    def paginate_subtree_documents(
        self,
        node_id: int,
        *,
        page: int,
        size: int,
        include_deleted_nodes: bool = False,
        include_deleted_documents: bool = False,
        include_descendants: bool = True,
        metadata_filters: MetadataFilters | None = None,
        search_query: str | None = None,
        doc_type: str | None = None,
        doc_ids: Sequence[int] | None = None,
    ) -> tuple[list[Document], int]:
        node = self._repo.get(node_id)
        if not node or (node.deleted_at is not None and not include_deleted_nodes):
            raise NodeNotFoundError("Node not found")

        node_ids: set[int]
        if include_descendants:
            self._repo.require_ltree()
            subtree_nodes = self._repo.fetch_subtree(
                node.path, include_deleted=include_deleted_nodes
            )
            node_ids = {n.id for n in subtree_nodes}
            node_ids.add(node.id)
        else:
            node_ids = {node.id}

        items, total = self._relationships.paginate_documents_for_nodes(
            sorted(node_ids),
            page=page,
            size=size,
            include_deleted_relations=include_deleted_nodes,
            include_deleted_documents=include_deleted_documents,
            metadata_filters=metadata_filters,
            search_query=search_query,
            doc_type=doc_type,
            doc_ids=doc_ids,
        )
        return items, total

    def paginate_subtree_documents_by_path(
        self,
        path: str,
        *,
        page: int,
        size: int,
        include_deleted_nodes: bool = False,
        include_deleted_documents: bool = False,
        include_descendants: bool = True,
        metadata_filters: MetadataFilters | None = None,
        search_query: str | None = None,
        doc_type: str | None = None,
        doc_ids: Sequence[int] | None = None,
    ) -> tuple[list[Document], int]:
        """通过节点路径获取子树下的文档列表。

        Args:
            path: 节点路径，如 "course.chapter"
            其他参数同 paginate_subtree_documents

        Returns:
            (文档列表, 总数)

        Raises:
            NodeNotFoundError: 节点不存在
        """
        node = self.get_node_by_path(path, include_deleted=include_deleted_nodes)
        return self.paginate_subtree_documents(
            node.id,
            page=page,
            size=size,
            include_deleted_nodes=include_deleted_nodes,
            include_deleted_documents=include_deleted_documents,
            include_descendants=include_descendants,
            metadata_filters=metadata_filters,
            search_query=search_query,
            doc_type=doc_type,
            doc_ids=doc_ids,
        )

    def recalculate_all_subtree_counts(self) -> dict:
        """全量重算所有节点的子树文档计数。

        采用自底向上策略：
        1. 重置所有节点计数为 0
        2. 遍历所有活跃的 output 类型文档绑定关系
        3. 对每个绑定，更新节点及其祖先链的计数

        Returns:
            包含统计信息的字典
        """
        from sqlalchemy import update as sql_update

        # 1. 重置所有节点计数为 0
        self.session.execute(sql_update(Node).values(subtree_doc_count=0))

        # 2. 获取所有活跃的 output 类型文档绑定关系（只统计活跃节点和活跃文档）
        active_bindings = self._relationships.list_active(
            node_id=None, document_id=None, relation_type=COUNTED_RELATION_TYPE
        )

        # 3. 统计每个祖先节点需要增加的计数
        ancestor_count_map: dict[int, int] = {}
        processed_bindings = 0

        for binding in active_bindings:
            node = self._repo.get(binding.node_id)
            if not node or node.deleted_at is not None:
                continue

            # 检查文档是否活跃
            doc = self.session.get(Document, binding.document_id)
            if not doc or doc.deleted_at is not None:
                continue

            # 获取祖先链并累加计数
            for ancestor_id in self._repo.get_ancestor_ids(node.path):
                ancestor_count_map[ancestor_id] = (
                    ancestor_count_map.get(ancestor_id, 0) + 1
                )
            processed_bindings += 1

        # 4. 批量更新所有祖先节点的计数
        for ancestor_id, count in ancestor_count_map.items():
            self._repo.update_subtree_counts([ancestor_id], count)

        self._commit()

        return {
            "processed_bindings": processed_bindings,
            "updated_nodes": len(ancestor_count_map),
        }
