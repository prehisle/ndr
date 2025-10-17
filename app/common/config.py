from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import os
from pathlib import Path


ENV_FILE = Path(".env.development")


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
    DB_URL: str = "sqlite:///./ndr.db"  # 默认 SQLite，.env 可覆写为 PostgreSQL
    ENABLE_METRICS: bool = True
    API_KEY_ENABLED: bool = False
    API_KEY: str | None = None
    CORS_ENABLED: bool = False
    CORS_ORIGINS: list[str] = field(default_factory=list)

    @classmethod
    def from_environment(cls) -> "Settings":
        _load_env_file()
        return cls(
            DB_URL=os.environ.get("DB_URL", cls.DB_URL),
            ENABLE_METRICS=_as_bool(os.environ.get("ENABLE_METRICS"), cls.ENABLE_METRICS),
            API_KEY_ENABLED=_as_bool(os.environ.get("API_KEY_ENABLED"), cls.API_KEY_ENABLED),
            API_KEY=os.environ.get("API_KEY"),
            CORS_ENABLED=_as_bool(os.environ.get("CORS_ENABLED"), cls.CORS_ENABLED),
            CORS_ORIGINS=_as_list(os.environ.get("CORS_ORIGINS")),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_environment()
