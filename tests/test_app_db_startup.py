import os
import contextlib

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from app.common.config import get_settings
from app.infra.db.session import engine
from app.infra.db.base import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@contextlib.contextmanager
def use_sqlite_memory():
    # Override DB_URL temporarily to in-memory sqlite for tests
    os.environ["DB_URL"] = "sqlite+pysqlite:///:memory:"
    try:
        # rebuild settings cache to pick new env
        get_settings.cache_clear()  # type: ignore[attr-defined]
        settings = get_settings()
        # patch engine & SessionLocal to use the new DB for the duration
        from app.infra.db import session as db_session
        db_session.engine = create_engine(settings.DB_URL, pool_pre_ping=True)
        db_session.SessionLocal = sessionmaker(
            bind=db_session.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        yield settings
    finally:
        # cleanup: restore cache
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_health_and_ready_endpoints_sqlite_memory():
    with use_sqlite_memory():
        app = create_app()
        client = TestClient(app)
        # startup will create tables
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}

        res2 = client.get("/ready")
        assert res2.status_code == 200
        assert res2.json().get("status") in {"ready", "not_ready"}


def test_tables_created_on_startup_sqlite_memory():
    with use_sqlite_memory():
        app = create_app()
        client = TestClient(app)
        # trigger startup
        client.get("/health")
        # verify metadata has tables
        # Note: using app.infra.db.base.Base metadata
        tables = set(Base.metadata.tables.keys())
        assert {"documents", "nodes", "node_documents"}.issubset(tables)