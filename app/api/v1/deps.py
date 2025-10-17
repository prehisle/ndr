from typing import Generator
from fastapi import Header, HTTPException
from app.infra.db.session import SessionLocal
from app.common.config import get_settings


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_request_context(x_user_id: str | None = Header(default=None), x_request_id: str | None = Header(default=None)):
    return {"user_id": x_user_id or "system", "request_id": x_request_id}


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if settings.API_KEY_ENABLED:
        api_key_expected = getattr(settings, "API_KEY", None)
        if not x_api_key or (api_key_expected and x_api_key != api_key_expected):
            raise HTTPException(status_code=401, detail="Invalid API key")