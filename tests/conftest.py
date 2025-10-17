from collections.abc import Generator
import os
import subprocess
from urllib.parse import urlparse
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.common.config import get_settings
from app.infra.db.base import Base


def _can_reach(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.scheme.startswith("postgresql"):
        return True
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    # 使用 nc / bash 工具探测端口是否开放
    try:
        subprocess.check_call(
            ["timeout", "1", "bash", "-lc", f"</dev/tcp/{host}/{port}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _create_engine(url: str):
    parsed = urlparse(url)
    connect_args: dict[str, object] = {}
    if parsed.scheme.startswith("postgresql"):
        connect_args["connect_timeout"] = 3
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    """
    Ensure each test starts with a clean schema when pointing to the shared PostgreSQL instance.
    If the environment overrides DB_URL (e.g. in-memory SQLite), this fixture still honours it.
    """
    settings = get_settings()
    db_url = settings.DB_URL
    fallback_triggered = False
    if not _can_reach(db_url):
        db_url = "sqlite+pysqlite:///:memory:"
        os.environ["DB_URL"] = db_url
        get_settings.cache_clear()  # type: ignore[attr-defined]
        settings = get_settings()
        fallback_triggered = True

    engine = _create_engine(settings.DB_URL)
    if fallback_triggered:
        from app.infra.db import session as db_session

        db_session.engine = engine
        db_session.SessionLocal = sessionmaker(
            bind=db_session.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        # 无法连接远端数据库时，再次回退至内存 SQLite
        sqlite_url = "sqlite+pysqlite:///:memory:"
        os.environ["DB_URL"] = sqlite_url
        get_settings.cache_clear()  # type: ignore[attr-defined]
        from app.infra.db import session as db_session

        db_session.engine = _create_engine(sqlite_url)
        db_session.SessionLocal = sessionmaker(
            bind=db_session.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        engine = db_session.engine
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        engine.dispose()
