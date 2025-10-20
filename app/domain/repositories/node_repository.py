from __future__ import annotations

from typing import Iterable, Sequence

from sqlalchemy import func, or_, select, text
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Session

from app.infra.db.models import Node
from app.infra.db.types import as_ltree, make_lquery


class LtreeNotAvailableError(RuntimeError):
    """Raised when ltree-specific operations are invoked on unsupported backends."""


class NodeRepository:
    def __init__(self, session: Session):
        self._session = session

    @property
    def session(self) -> Session:
        return self._session

    def _dialect(self) -> Dialect | None:
        bind = self._session.get_bind()
        return bind.dialect if bind is not None else None

    def get(self, node_id: int) -> Node | None:
        return self._session.get(Node, node_id)

    def get_active_by_path(self, path: str) -> Node | None:
        stmt = select(Node).where(Node.deleted_at.is_(None), Node.path == path)
        return self._session.execute(stmt).scalar_one_or_none()

    def has_active_path(self, path: str, *, exclude_id: int | None = None) -> bool:
        stmt = select(Node.id).where(Node.deleted_at.is_(None), Node.path == path)
        if exclude_id is not None:
            stmt = stmt.where(Node.id != exclude_id)
        return self._session.execute(stmt).scalar_one_or_none() is not None

    def has_active_name(
        self, parent_path: str | None, name: str, *, exclude_id: int | None = None
    ) -> bool:
        stmt = select(Node.id).where(Node.deleted_at.is_(None), Node.name == name)
        if parent_path is None:
            stmt = stmt.where(Node.parent_path.is_(None))
        else:
            stmt = stmt.where(Node.parent_path == parent_path)
        if exclude_id is not None:
            stmt = stmt.where(Node.id != exclude_id)
        return self._session.execute(stmt).scalar_one_or_none() is not None

    def _with_parent_filter(self, stmt, parent_id: int | None):
        if parent_id is None:
            return stmt.where(Node.parent_id.is_(None))
        return stmt.where(Node.parent_id == parent_id)

    def next_position(self, parent_id: int | None) -> int:
        stmt = select(func.coalesce(func.max(Node.position), -1) + 1)
        stmt = self._with_parent_filter(stmt, parent_id)
        stmt = stmt.where(Node.deleted_at.is_(None))
        return self._session.execute(stmt).scalar_one()

    def fetch_siblings(
        self,
        parent_id: int | None,
        *,
        include_deleted: bool,
        order_by_position: bool = True,
    ) -> Sequence[Node]:
        stmt = select(Node)
        stmt = self._with_parent_filter(stmt, parent_id)
        if not include_deleted:
            stmt = stmt.where(Node.deleted_at.is_(None))
        if order_by_position:
            stmt = stmt.order_by(Node.position, Node.id)
        return tuple(self._session.execute(stmt).scalars())

    def normalize_positions(
        self, parent_id: int | None, *, include_deleted: bool = False
    ) -> None:
        siblings = list(
            self.fetch_siblings(
                parent_id,
                include_deleted=include_deleted,
                order_by_position=True,
            )
        )
        for index, node in enumerate(siblings):
            if node.position != index:
                node.position = index

    def require_ltree(self) -> None:
        dialect = self._dialect()
        if dialect is None or dialect.name != "postgresql":
            raise LtreeNotAvailableError("PostgreSQL with ltree extension is required")

    def lock_nodes(self, node_ids: Iterable[int]) -> None:
        ids = sorted(set(node_ids))
        if not ids:
            return
        for node_id in ids:
            self._session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": node_id}
            )

    def fetch_descendants(self, root_path: str, *, exclude_id: int) -> Sequence[Node]:
        pattern = f"{root_path}.*{{1,}}"
        path_expr = as_ltree(Node.path)
        stmt = (
            select(Node)
            .where(Node.id != exclude_id)
            .where(path_expr.op("~")(make_lquery(pattern)))
        )
        return tuple(self._session.execute(stmt).scalars())

    def fetch_children(self, node_path: str, depth: int) -> Sequence[Node]:
        pattern = f"{node_path}.*{{1,{depth}}}"
        path_expr = as_ltree(Node.path)
        stmt = (
            select(Node)
            .where(Node.deleted_at.is_(None))
            .where(path_expr.op("~")(make_lquery(pattern)))
            .order_by(Node.parent_id, Node.position, Node.id)
        )
        return tuple(self._session.execute(stmt).scalars())

    def fetch_subtree(self, root_path: str, *, include_deleted: bool) -> Sequence[Node]:
        pattern = f"{root_path}.*{{1,}}"
        path_expr = as_ltree(Node.path)
        stmt = select(Node).where(
            or_(Node.path == root_path, path_expr.op("~")(make_lquery(pattern)))
        )
        if not include_deleted:
            stmt = stmt.where(Node.deleted_at.is_(None))
        stmt = stmt.order_by(Node.path)
        return tuple(self._session.execute(stmt).scalars())

    def paginate_nodes(
        self, page: int, size: int, include_deleted: bool
    ) -> tuple[list[Node], int]:
        base_stmt = select(Node)
        count_stmt = select(func.count()).select_from(Node)
        if not include_deleted:
            base_stmt = base_stmt.where(Node.deleted_at.is_(None))
            count_stmt = count_stmt.where(Node.deleted_at.is_(None))
        base_stmt = (
            base_stmt.order_by(Node.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        items = list(self._session.execute(base_stmt).scalars())
        total = self._session.execute(count_stmt).scalar_one()
        return items, total
