from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.common.config import get_settings


def test_startup_runs_alembic_upgrade(monkeypatch):
    calls: list[bool] = []

    def fake_upgrade() -> None:
        calls.append(True)

    monkeypatch.setenv("AUTO_APPLY_MIGRATIONS", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    monkeypatch.setattr("app.main.upgrade_to_head", fake_upgrade)

    app = create_app()
    with TestClient(app):
        pass

    assert calls, "upgrade_to_head should be invoked during startup"
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_startup_skips_alembic_when_disabled(monkeypatch):
    calls: list[bool] = []

    def fake_upgrade() -> None:
        calls.append(True)

    monkeypatch.setenv("AUTO_APPLY_MIGRATIONS", "false")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    monkeypatch.setattr("app.main.upgrade_to_head", fake_upgrade)

    app = create_app()
    with TestClient(app):
        pass

    assert not calls, "upgrade_to_head should be skipped when auto-apply is disabled"
    get_settings.cache_clear()  # type: ignore[attr-defined]
