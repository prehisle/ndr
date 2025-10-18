from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.common.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _build_connect_args(db_url: str, timeout: int) -> dict[str, Any]:
    if db_url.lower().startswith("postgresql"):
        return {"connect_timeout": timeout}
    return {}


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.DB_URL,
            pool_pre_ping=True,
            future=True,
            connect_args=_build_connect_args(
                settings.DB_URL, settings.DB_CONNECT_TIMEOUT
            ),
        )
        _SessionLocal = sessionmaker(
            bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False
        )
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
