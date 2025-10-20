import logging
from typing import Generator

from fastapi import Header, HTTPException

from app.common.config import get_settings
from app.infra.db.session import get_session_factory


def get_db() -> Generator:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_request_context(
    x_user_id: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
):
    user_id = x_user_id if x_user_id not in (None, "") else "<missing>"
    return {
        "user_id": user_id,
        "request_id": x_request_id,
        "user_supplied": x_user_id if x_user_id is not None else None,
    }


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if settings.API_KEY_ENABLED:
        api_key_expected = getattr(settings, "API_KEY", None)
        if not x_api_key or (api_key_expected and x_api_key != api_key_expected):
            raise HTTPException(status_code=401, detail="Invalid API key")


def require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    admin_key = getattr(settings, "DESTRUCTIVE_API_KEY", None)
    if not admin_key:
        raise HTTPException(status_code=503, detail="Permanent delete is disabled")
    if x_admin_key != admin_key:
        logger = logging.getLogger("http")
        preview = "<missing>"
        if x_admin_key:
            preview = f"{x_admin_key[:4]}***"
        logger.warning(
            "admin_key_mismatch admin_key_preview=%s",
            preview,
        )
        raise HTTPException(status_code=403, detail="Forbidden")
