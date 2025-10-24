from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ENV_FILE = Path(".env")

DEFAULT_AUTH_ROLES: tuple[str, ...] = ("anonymous",)
DEFAULT_AUTH_PERMISSIONS: tuple[str, ...] = ("*",)


def _load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "t", "yes", "y", "on"}


def _as_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    DB_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/ndr"
    DB_CONNECT_TIMEOUT: int = 5
    ENABLE_METRICS: bool = True
    API_KEY_ENABLED: bool = False
    API_KEY: str | None = None
    DESTRUCTIVE_API_KEY: str | None = None
    CORS_ENABLED: bool = False
    CORS_ORIGINS: list[str] = field(default_factory=list)
    AUTO_APPLY_MIGRATIONS: bool = True
    TRACE_HTTP: bool = False
    AUTH_ENABLED: bool = False
    AUTH_ALLOW_ANONYMOUS: bool = False
    AUTH_TOKEN_SECRET: str | None = None
    AUTH_TOKEN_ALGORITHM: str = "HS256"
    AUTH_TOKEN_AUDIENCE: str | None = None
    AUTH_TOKEN_ISSUER: str | None = None
    AUTH_TOKEN_LEEWAY: int = 0
    AUTH_DEFAULT_ROLES: list[str] = field(
        default_factory=lambda: list(DEFAULT_AUTH_ROLES)
    )
    AUTH_DEFAULT_PERMISSIONS: list[str] = field(
        default_factory=lambda: list(DEFAULT_AUTH_PERMISSIONS)
    )

    def __post_init__(self) -> None:
        db_scheme = self.DB_URL.split(":", 1)[0].lower()
        if not db_scheme.startswith("postgresql"):
            raise ValueError(
                "DB_URL must point to a PostgreSQL datasource (postgresql+driver://...)."
            )

    @classmethod
    def from_environment(cls) -> "Settings":
        _load_env_file()
        db_url = os.environ.get("DB_URL", cls.DB_URL)
        auth_default_roles_env = os.environ.get("AUTH_DEFAULT_ROLES")
        if auth_default_roles_env is None:
            auth_default_roles = list(DEFAULT_AUTH_ROLES)
        else:
            auth_default_roles = _as_list(auth_default_roles_env)

        auth_default_permissions_env = os.environ.get("AUTH_DEFAULT_PERMISSIONS")
        if auth_default_permissions_env is None:
            auth_default_permissions = list(DEFAULT_AUTH_PERMISSIONS)
        else:
            auth_default_permissions = _as_list(auth_default_permissions_env)

        return cls(
            DB_URL=db_url,
            DB_CONNECT_TIMEOUT=int(
                os.environ.get("DB_CONNECT_TIMEOUT", cls.DB_CONNECT_TIMEOUT)
            ),
            ENABLE_METRICS=_as_bool(
                os.environ.get("ENABLE_METRICS"), cls.ENABLE_METRICS
            ),
            API_KEY_ENABLED=_as_bool(
                os.environ.get("API_KEY_ENABLED"), cls.API_KEY_ENABLED
            ),
            API_KEY=os.environ.get("API_KEY"),
            DESTRUCTIVE_API_KEY=os.environ.get("DESTRUCTIVE_API_KEY"),
            CORS_ENABLED=_as_bool(os.environ.get("CORS_ENABLED"), cls.CORS_ENABLED),
            CORS_ORIGINS=_as_list(os.environ.get("CORS_ORIGINS")),
            AUTO_APPLY_MIGRATIONS=_as_bool(
                os.environ.get("AUTO_APPLY_MIGRATIONS"), cls.AUTO_APPLY_MIGRATIONS
            ),
            TRACE_HTTP=_as_bool(os.environ.get("TRACE_HTTP"), cls.TRACE_HTTP),
            AUTH_ENABLED=_as_bool(os.environ.get("AUTH_ENABLED"), cls.AUTH_ENABLED),
            AUTH_ALLOW_ANONYMOUS=_as_bool(
                os.environ.get("AUTH_ALLOW_ANONYMOUS"), cls.AUTH_ALLOW_ANONYMOUS
            ),
            AUTH_TOKEN_SECRET=os.environ.get("AUTH_TOKEN_SECRET"),
            AUTH_TOKEN_ALGORITHM=os.environ.get(
                "AUTH_TOKEN_ALGORITHM", cls.AUTH_TOKEN_ALGORITHM
            ),
            AUTH_TOKEN_AUDIENCE=os.environ.get("AUTH_TOKEN_AUDIENCE"),
            AUTH_TOKEN_ISSUER=os.environ.get("AUTH_TOKEN_ISSUER"),
            AUTH_TOKEN_LEEWAY=int(
                os.environ.get("AUTH_TOKEN_LEEWAY", cls.AUTH_TOKEN_LEEWAY)
            ),
            AUTH_DEFAULT_ROLES=auth_default_roles,
            AUTH_DEFAULT_PERMISSIONS=auth_default_permissions,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_environment()
