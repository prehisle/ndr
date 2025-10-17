from collections.abc import Generator
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.common.config import get_settings
from app.infra.db.base import Base


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    """
    Ensure each test starts with a clean schema when pointing to the shared PostgreSQL instance.
    If the environment overrides DB_URL (e.g. in-memory SQLite), this fixture still honours it.
    """
    settings = get_settings()
    engine = create_engine(settings.DB_URL, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"数据库连接失败，请确认 PostgreSQL 服务可达: {exc}")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        engine.dispose()
