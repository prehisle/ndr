"""测试 /ready 端点的各种场景（使用 Mock 避免真实数据库依赖）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.v1.deps import get_db
from app.common.config import get_settings


@dataclass
class _FakeDialect:
    """模拟 SQLAlchemy dialect。"""

    name: str


@dataclass
class _FakeBind:
    """模拟 SQLAlchemy bind。"""

    dialect: _FakeDialect


class _FakeScalar:
    """模拟 SQLAlchemy execute 结果。"""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeInspector:
    """模拟 SQLAlchemy inspector。"""

    def __init__(self, table_names: list[str]) -> None:
        self._table_names = table_names

    def get_table_names(self) -> list[str]:
        return list(self._table_names)


class _FakeSession:
    """模拟 SQLAlchemy Session，支持各种测试场景。"""

    def __init__(
        self,
        *,
        dialect_name: str,
        table_names: list[str],
        current_revision: str | None = None,
        ltree_enabled: bool = True,
        raise_on_select1: bool = False,
    ) -> None:
        self._bind = _FakeBind(_FakeDialect(dialect_name))
        self._table_names = table_names
        self._current_revision = current_revision
        self._ltree_enabled = ltree_enabled
        self._raise_on_select1 = raise_on_select1

    def get_bind(self) -> _FakeBind:
        return self._bind

    def execute(self, statement: Any) -> _FakeScalar:
        text_value = getattr(statement, "text", str(statement))

        # SELECT 1 健康检查
        if "SELECT 1" in text_value and "pg_extension" not in text_value:
            if self._raise_on_select1:
                raise OperationalError("SELECT 1", {}, Exception("db down"))
            return _FakeScalar(1)

        # alembic 版本查询
        if "FROM alembic_version" in text_value:
            return _FakeScalar(self._current_revision)

        # ltree 扩展检查
        if "FROM pg_extension" in text_value and "ltree" in text_value:
            return _FakeScalar(1 if self._ltree_enabled else None)

        return _FakeScalar(None)


def _required_tables() -> list[str]:
    """返回系统所需的表列表。"""
    return [
        "documents",
        "nodes",
        "node_documents",
        "assets",
        "node_assets",
        "idempotency_records",
    ]


class TestReadyEndpoint:
    """测试 /ready 端点。"""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """每个测试前清除配置缓存。"""
        monkeypatch.setenv("AUTO_APPLY_MIGRATIONS", "false")
        get_settings.cache_clear()  # type: ignore[attr-defined]

    def test_reports_missing_tables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缺少必需表时应该报告 missing_tables。"""
        import app.main as main_mod

        app = main_mod.create_app()

        fake_session = _FakeSession(
            dialect_name="postgresql",
            table_names=["documents"],  # 只有一个表
            current_revision="rev_head",
            ltree_enabled=True,
        )

        def override_get_db():
            yield fake_session

        app.dependency_overrides[get_db] = override_get_db
        monkeypatch.setattr(
            main_mod,
            "inspect",
            lambda bind: _FakeInspector(fake_session._table_names),
        )
        monkeypatch.setattr(main_mod, "get_head_revision", lambda: "rev_head")

        client = TestClient(app)
        r = client.get("/ready")

        assert r.status_code == 200
        payload = r.json()
        assert payload["status"] == "not_ready"
        assert "missing_tables" in payload["detail"]
        assert "nodes" in payload["detail"]["missing_tables"]

    def test_reports_migrations_out_of_date(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """迁移版本落后时应该报告 out_of_date。"""
        import app.main as main_mod

        app = main_mod.create_app()

        fake_session = _FakeSession(
            dialect_name="postgresql",
            table_names=_required_tables(),
            current_revision="rev_old",  # 旧版本
            ltree_enabled=True,
        )

        def override_get_db():
            yield fake_session

        app.dependency_overrides[get_db] = override_get_db
        monkeypatch.setattr(
            main_mod,
            "inspect",
            lambda bind: _FakeInspector(fake_session._table_names),
        )
        monkeypatch.setattr(main_mod, "get_head_revision", lambda: "rev_head")

        client = TestClient(app)
        r = client.get("/ready")

        assert r.status_code == 200
        payload = r.json()
        assert payload["status"] == "not_ready"
        detail = payload["detail"]
        assert "migrations" in detail
        assert detail["migrations"]["status"] == "out_of_date"
        assert detail["migrations"]["current"] == "rev_old"
        assert detail["migrations"]["expected"] == "rev_head"

    def test_reports_ltree_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ltree 扩展缺失时应该报告 ltree_extension: missing。"""
        import app.main as main_mod

        app = main_mod.create_app()

        fake_session = _FakeSession(
            dialect_name="postgresql",
            table_names=_required_tables(),
            current_revision="rev_head",
            ltree_enabled=False,  # ltree 未启用
        )

        def override_get_db():
            yield fake_session

        app.dependency_overrides[get_db] = override_get_db
        monkeypatch.setattr(
            main_mod,
            "inspect",
            lambda bind: _FakeInspector(fake_session._table_names),
        )
        monkeypatch.setattr(main_mod, "get_head_revision", lambda: "rev_head")

        client = TestClient(app)
        r = client.get("/ready")

        assert r.status_code == 200
        payload = r.json()
        assert payload["status"] == "not_ready"
        assert payload["detail"]["ltree_extension"] == "missing"

    def test_reports_ready_for_non_postgres(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """非 PostgreSQL 数据库在表齐全时应该报告 ready。"""
        import app.main as main_mod

        app = main_mod.create_app()

        fake_session = _FakeSession(
            dialect_name="sqlite",  # 非 PostgreSQL
            table_names=_required_tables(),
            current_revision=None,
            ltree_enabled=True,
        )

        def override_get_db():
            yield fake_session

        app.dependency_overrides[get_db] = override_get_db
        monkeypatch.setattr(
            main_mod,
            "inspect",
            lambda bind: _FakeInspector(fake_session._table_names),
        )

        client = TestClient(app)
        r = client.get("/ready")

        assert r.status_code == 200
        assert r.json() == {"status": "ready"}

    def test_handles_operational_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """数据库连接失败时应该报告 not_ready。"""
        import app.main as main_mod

        app = main_mod.create_app()

        fake_session = _FakeSession(
            dialect_name="postgresql",
            table_names=_required_tables(),
            current_revision="rev_head",
            ltree_enabled=True,
            raise_on_select1=True,  # SELECT 1 时抛出异常
        )

        def override_get_db():
            yield fake_session

        app.dependency_overrides[get_db] = override_get_db
        monkeypatch.setattr(
            main_mod,
            "inspect",
            lambda bind: _FakeInspector(fake_session._table_names),
        )

        client = TestClient(app)
        r = client.get("/ready")

        assert r.status_code == 200
        payload = r.json()
        assert payload["status"] == "not_ready"
        assert "db" in payload["detail"]
