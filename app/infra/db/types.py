from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import bindparam, cast
from sqlalchemy.sql.elements import BindParameter
from sqlalchemy.types import String, TypeDecorator, UserDefinedType

try:  # Optional dependency; SQLAlchemy does not import ltree by default.
    from sqlalchemy.dialects.postgresql import ltree as _pg_ltree  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - fallback when ltree dialect is unavailable
    _pg_ltree = None


class _FallbackLtree(UserDefinedType):  # pragma: no cover - exercised via integration tests
    def get_col_spec(self, **kw: Any) -> str:
        return "LTREE"

    def bind_processor(self, dialect):
        return lambda value: value

    def result_processor(self, dialect, coltype):
        return lambda value: value


class _FallbackLquery(UserDefinedType):  # pragma: no cover - exercised via integration tests
    def get_col_spec(self, **kw: Any) -> str:
        return "LQUERY"

    def bind_processor(self, dialect):
        return lambda value: value

    def result_processor(self, dialect, coltype):
        return lambda value: value


def _new_ltree_type():
    if _pg_ltree is not None:
        return _pg_ltree.LTREE()
    return _FallbackLtree()


def _new_lquery_type():
    if _pg_ltree is not None:
        return _pg_ltree.LQUERY()
    return _FallbackLquery()


def _make_bind_param(value: str, prefix: str) -> BindParameter[str]:
    return bindparam(f"{prefix}_{uuid.uuid4().hex}", value)


def make_lquery(pattern: str):
    """Return a SQL expression that casts the given pattern into a lquery literal."""

    return cast(_make_bind_param(pattern, "lquery"), _new_lquery_type())


def make_ltree(value: str):
    """Return a SQL expression that casts the given value into a ltree literal."""

    return cast(_make_bind_param(value, "ltree"), _new_ltree_type())


def as_ltree(expression):
    """Cast an arbitrary SQL expression to ltree, relying on the extended type."""

    return cast(expression, _new_ltree_type())


HAS_POSTGRES_LTREE = _pg_ltree is not None


class LtreeType(TypeDecorator):
    """Dialect-aware ltree column.

    Falls back to plain string storage on non-PostgreSQL backends or when the
    optional SQLAlchemy ltree dialect is not installed. This keeps local tests
    working with SQLite while production systems can depend on PostgreSQL's
    native ltree type.
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int = 2048, **kwargs: Any) -> None:
        super().__init__(length=length, **kwargs)
        self._length = length

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_new_ltree_type())
        return dialect.type_descriptor(String(self._length))

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value
