from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.common.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def get_alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", get_settings().DB_URL)
    return config


def get_head_revision() -> str | None:
    config = get_alembic_config()
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


def upgrade_to_head() -> None:
    config = get_alembic_config()
    command.upgrade(config, "head")
