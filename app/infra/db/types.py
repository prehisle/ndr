from __future__ import annotations

from typing import Any

from sqlalchemy.types import String, TypeDecorator

try:  # Optional dependency; SQLAlchemy does not import ltree by default.
    from sqlalchemy.dialects.postgresql import ltree as _pg_ltree  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - fallback when ltree dialect is unavailable
    _pg_ltree = None

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
        if dialect.name == "postgresql" and _pg_ltree is not None:
            return dialect.type_descriptor(_pg_ltree.LTREE())
        return dialect.type_descriptor(String(self._length))

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value
