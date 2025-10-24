from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, MutableMapping

import jwt
from jwt import PyJWTError

from app.common.config import Settings

logger = logging.getLogger("auth")


class AuthenticationError(Exception):
    """Raised when authentication fails."""


@dataclass(frozen=True)
class Principal:
    user_id: str
    roles: frozenset[str]
    permissions: frozenset[str]
    token: str | None
    claims: Mapping[str, Any]
    source: str

    def has_permission(self, permission: str) -> bool:
        if "*" in self.permissions:
            return True
        if permission in self.permissions:
            return True
        parts = permission.split(":")
        if len(parts) <= 1:
            return False
        # support hierarchical wildcards like "documents:*"
        for index in range(len(parts), 0, -1):
            candidate = ":".join(list(parts[: index - 1]) + ["*"])
            if candidate in self.permissions:
                return True
        return False

    def has_all_permissions(self, permissions: Iterable[str]) -> bool:
        return all(self.has_permission(permission) for permission in permissions)

    def has_any_permission(self, permissions: Iterable[str]) -> bool:
        return any(self.has_permission(permission) for permission in permissions)

    def has_role(self, role: str) -> bool:
        if role == "*":
            return True
        return role in self.roles

    def has_any_role(self, roles: Iterable[str]) -> bool:
        return any(self.has_role(role) for role in roles)

    def missing_permissions(self, permissions: Iterable[str]) -> list[str]:
        return [
            permission
            for permission in permissions
            if not self.has_permission(permission)
        ]

    def missing_roles(self, roles: Iterable[str]) -> list[str]:
        return [role for role in roles if not self.has_role(role)]


class Authenticator:
    def __init__(self, settings: Settings):
        self._settings = settings

    def authenticate(
        self,
        authorization_header: str | None,
        fallback_user_id: str | None,
    ) -> Principal:
        if not self._settings.AUTH_ENABLED:
            return self._build_principal_from_headers(fallback_user_id, source="legacy")

        if not authorization_header or authorization_header.strip().lower() == "bearer":
            if self._settings.AUTH_ALLOW_ANONYMOUS:
                return self._build_principal_from_headers(
                    fallback_user_id,
                    source="anonymous",
                )
            raise AuthenticationError("Missing bearer token")

        scheme, _, credentials = authorization_header.partition(" ")
        if scheme.lower() != "bearer" or not credentials.strip():
            raise AuthenticationError("Invalid authorization header")

        token = credentials.strip()
        claims = self._decode_token(token)

        subject = claims.get("sub")
        if not subject:
            raise AuthenticationError("Token missing 'sub' claim")

        roles = _ensure_list(claims.get("roles") or claims.get("role"))
        default_roles = [role for role in self._settings.AUTH_DEFAULT_ROLES if role]
        default_permissions = [
            permission
            for permission in self._settings.AUTH_DEFAULT_PERMISSIONS
            if permission
        ]
        permissions: set[str] = set(default_permissions)
        permissions.update(
            _ensure_list(claims.get("permissions") or claims.get("perms"))
        )
        permissions.update(_ensure_scopes(claims.get("scope")))
        permissions.update(_ensure_list(claims.get("scopes")))

        resolved_roles = frozenset(roles or default_roles)
        resolved_permissions = frozenset(permissions)

        return Principal(
            user_id=str(subject),
            roles=resolved_roles,
            permissions=resolved_permissions,
            token=token,
            claims=claims,
            source="bearer",
        )

    def _build_principal_from_headers(
        self,
        fallback_user_id: str | None,
        *,
        source: str,
    ) -> Principal:
        user_id = (
            fallback_user_id if fallback_user_id not in (None, "") else "<missing>"
        )
        roles = frozenset(self._settings.AUTH_DEFAULT_ROLES)
        permissions = frozenset(self._settings.AUTH_DEFAULT_PERMISSIONS or ["*"])
        return Principal(
            user_id=user_id,
            roles=roles,
            permissions=permissions,
            token=None,
            claims={},
            source=source,
        )

    def _decode_token(self, token: str) -> MutableMapping[str, Any]:
        secret = self._settings.AUTH_TOKEN_SECRET
        if not secret:
            raise AuthenticationError(
                "Authentication secret is not configured while AUTH_ENABLED is true"
            )

        decode_kwargs: dict[str, Any] = {
            "algorithms": [self._settings.AUTH_TOKEN_ALGORITHM],
        }
        if self._settings.AUTH_TOKEN_AUDIENCE:
            decode_kwargs["audience"] = self._settings.AUTH_TOKEN_AUDIENCE
        if self._settings.AUTH_TOKEN_ISSUER:
            decode_kwargs["issuer"] = self._settings.AUTH_TOKEN_ISSUER
        if self._settings.AUTH_TOKEN_LEEWAY:
            decode_kwargs["leeway"] = self._settings.AUTH_TOKEN_LEEWAY

        try:
            return jwt.decode(token, secret, **decode_kwargs)
        except PyJWTError as exc:  # pragma: no cover - safety net
            logger.debug("token_decode_error", exc_info=exc)
            raise AuthenticationError("Invalid authentication token") from exc


def _ensure_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return []


def _ensure_scopes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item for item in value.split() if item]
    if isinstance(value, (list, tuple, set)):
        scopes: list[str] = []
        for item in value:
            if isinstance(item, str):
                scopes.extend(token for token in item.split() if token)
        return scopes
    return []
