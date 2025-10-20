from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
from sqlalchemy import text

from app.common.config import get_settings  # noqa: E402


def _resolve_test_db_url() -> str:
    explicit = os.environ.get("TEST_DB_URL") or os.environ.get("DB_URL")
    if explicit:
        return explicit
    settings = get_settings()
    return settings.DB_URL


test_db_url = _resolve_test_db_url()
if not test_db_url:
    raise RuntimeError("Provide TEST_DB_URL or DB_URL for PostgreSQL-backed tests.")

if not test_db_url.lower().startswith("postgresql"):
    raise RuntimeError(
        "Tests require a PostgreSQL connection string (postgresql+driver://...)."
    )

os.environ["DB_URL"] = test_db_url
os.environ.setdefault("AUTO_APPLY_MIGRATIONS", "true")
os.environ["DESTRUCTIVE_API_KEY"] = os.environ.get("DESTRUCTIVE_API_KEY") or "admin-secret"
get_settings.cache_clear()  # type: ignore[attr-defined]
from app.infra.db.alembic_support import upgrade_to_head  # noqa: E402
from app.infra.db.session import get_session_factory, reset_engine  # noqa: E402


@contextmanager
def _session_scope():
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    get_settings.cache_clear()  # type: ignore[attr-defined]
    reset_engine()
    upgrade_to_head()
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def cleanup_tables(apply_migrations):
    with _session_scope() as session:
        session.execute(
            text(
                "TRUNCATE idempotency_records, node_documents, nodes, documents RESTART IDENTITY CASCADE"
            )
        )
    yield
    with _session_scope() as session:
        session.execute(
            text(
                "TRUNCATE idempotency_records, node_documents, nodes, documents RESTART IDENTITY CASCADE"
            )
        )
