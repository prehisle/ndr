from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ENV_FILE = Path(".env")

_ONE_GIB = 1024 * 1024 * 1024
_FIVE_MIB = 5 * 1024 * 1024
_SIXTEEN_MIB = 16 * 1024 * 1024


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
    # Database
    DB_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/ndr"
    DB_CONNECT_TIMEOUT: int = 5

    # Metrics & Observability
    ENABLE_METRICS: bool = True
    TRACE_HTTP: bool = False

    # API Key Authentication
    API_KEY_ENABLED: bool = False
    API_KEY: str | None = None
    DESTRUCTIVE_API_KEY: str | None = None

    # CORS
    CORS_ENABLED: bool = False
    CORS_ORIGINS: list[str] = field(default_factory=list)

    # Database Migrations
    AUTO_APPLY_MIGRATIONS: bool = True

    # Object Storage (S3-compatible)
    STORAGE_BACKEND: str = "s3"
    STORAGE_MAX_UPLOAD_BYTES: int = _ONE_GIB
    STORAGE_PART_SIZE_BYTES: int = _SIXTEEN_MIB
    STORAGE_PRESIGN_EXPIRES_SECONDS: int = 15 * 60

    # S3 Configuration
    S3_ENDPOINT_URL: str | None = None
    S3_REGION: str | None = None
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None
    S3_BUCKET: str = "ndr-assets"
    S3_PREFIX: str = "assets/"
    S3_USE_SSL: bool = True
    S3_ADDRESSING_STYLE: str = "path"
    # Public URL base for direct access (e.g., "http://192.168.1.4:9005/ndr-assets")
    # When set, download URLs will be public URLs instead of presigned URLs
    S3_PUBLIC_URL_BASE: str | None = None

    def __post_init__(self) -> None:
        db_scheme = self.DB_URL.split(":", 1)[0].lower()
        if not db_scheme.startswith("postgresql"):
            raise ValueError(
                "DB_URL must point to a PostgreSQL datasource (postgresql+driver://...)."
            )
        if self.STORAGE_PART_SIZE_BYTES < _FIVE_MIB:
            raise ValueError(
                "STORAGE_PART_SIZE_BYTES must be >= 5 MiB (S3 requirement)"
            )
        if self.STORAGE_MAX_UPLOAD_BYTES <= 0:
            raise ValueError("STORAGE_MAX_UPLOAD_BYTES must be positive")
        if self.STORAGE_PRESIGN_EXPIRES_SECONDS <= 0:
            raise ValueError("STORAGE_PRESIGN_EXPIRES_SECONDS must be positive")

    @classmethod
    def from_environment(cls) -> "Settings":
        _load_env_file()
        db_url = os.environ.get("DB_URL", cls.DB_URL)
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
            # Storage
            STORAGE_BACKEND=os.environ.get("STORAGE_BACKEND", cls.STORAGE_BACKEND),
            STORAGE_MAX_UPLOAD_BYTES=int(
                os.environ.get("STORAGE_MAX_UPLOAD_BYTES", cls.STORAGE_MAX_UPLOAD_BYTES)
            ),
            STORAGE_PART_SIZE_BYTES=int(
                os.environ.get("STORAGE_PART_SIZE_BYTES", cls.STORAGE_PART_SIZE_BYTES)
            ),
            STORAGE_PRESIGN_EXPIRES_SECONDS=int(
                os.environ.get(
                    "STORAGE_PRESIGN_EXPIRES_SECONDS",
                    cls.STORAGE_PRESIGN_EXPIRES_SECONDS,
                )
            ),
            # S3
            S3_ENDPOINT_URL=os.environ.get("S3_ENDPOINT_URL"),
            S3_REGION=os.environ.get("S3_REGION"),
            S3_ACCESS_KEY_ID=os.environ.get("S3_ACCESS_KEY_ID"),
            S3_SECRET_ACCESS_KEY=os.environ.get("S3_SECRET_ACCESS_KEY"),
            S3_BUCKET=os.environ.get("S3_BUCKET", cls.S3_BUCKET),
            S3_PREFIX=os.environ.get("S3_PREFIX", cls.S3_PREFIX),
            S3_USE_SSL=_as_bool(os.environ.get("S3_USE_SSL"), cls.S3_USE_SSL),
            S3_ADDRESSING_STYLE=os.environ.get(
                "S3_ADDRESSING_STYLE", cls.S3_ADDRESSING_STYLE
            ),
            S3_PUBLIC_URL_BASE=os.environ.get("S3_PUBLIC_URL_BASE"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_environment()
