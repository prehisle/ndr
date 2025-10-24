from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Generator

from fastapi import Depends, Header, HTTPException

from app.common.auth import AuthenticationError, Authenticator, Principal
from app.common.config import get_settings
from app.infra.db.session import get_session_factory

logger = logging.getLogger("http")


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


def get_current_principal(
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> Principal:
    authenticator = Authenticator(get_settings())
    try:
        return authenticator.authenticate(
            authorization_header=authorization,
            fallback_user_id=x_user_id,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "message": str(exc),
                "error_code": "unauthenticated",
            },
        ) from exc


def get_request_context(
    principal: Principal = Depends(get_current_principal),
    x_request_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
):
    user_supplied = x_user_id if x_user_id not in (None, "") else None
    return {
        "user_id": principal.user_id,
        "request_id": x_request_id,
        "user_supplied": user_supplied,
        "principal": principal,
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
        preview = "<missing>"
        if x_admin_key:
            preview = f"{x_admin_key[:4]}***"
        logger.warning(
            "admin_key_mismatch admin_key_preview=%s",
            preview,
        )
        raise HTTPException(status_code=403, detail="Forbidden")


def require_permissions(*permissions: str) -> Callable[[], None]:
    if not permissions:
        raise ValueError("At least one permission must be provided")

    def dependency(principal: Principal = Depends(get_current_principal)) -> None:
        missing = principal.missing_permissions(permissions)
        if missing:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Missing required permissions",
                    "missing_permissions": missing,
                    "error_code": "permission_denied",
                },
            )

    return dependency


def require_permission(permission: str) -> Callable[[], None]:
    return require_permissions(permission)


def require_roles(*roles: str) -> Callable[[], None]:
    if not roles:
        raise ValueError("At least one role must be provided")

    def dependency(principal: Principal = Depends(get_current_principal)) -> None:
        missing = principal.missing_roles(roles)
        if missing:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Missing required roles",
                    "missing_roles": missing,
                    "error_code": "insufficient_roles",
                },
            )

    return dependency


def require_role(role: str) -> Callable[[], None]:
    return require_roles(role)
