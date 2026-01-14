"""测试 app/main.py 中的辅助函数。"""

from __future__ import annotations

from app.main import (
    _collect_db_metadata,
    _describe_db_target,
    _format_db_context,
    _normalize_detail,
    _resolve_error_code,
)


class TestNormalizeDetail:
    """测试 _normalize_detail 函数。"""

    def test_unwraps_message_and_extracts_error_code(self) -> None:
        """包含 message 和 error_code 的字典应该正确解包。"""
        detail, code = _normalize_detail({"message": "x", "error_code": "custom"})
        assert detail == "x"
        assert code == "custom"

    def test_strips_error_code_and_handles_empty(self) -> None:
        """只有 error_code 的字典应该返回 None detail。"""
        detail, code = _normalize_detail({"error_code": "custom"})
        assert detail is None
        assert code == "custom"

    def test_ignores_non_string_error_code(self) -> None:
        """非字符串的 error_code 应该被忽略。"""
        detail, code = _normalize_detail({"message": "x", "error_code": 123})
        assert detail == "x"
        assert code is None

    def test_returns_string_detail_as_is(self) -> None:
        """字符串 detail 应该原样返回。"""
        detail, code = _normalize_detail("simple error")
        assert detail == "simple error"
        assert code is None

    def test_preserves_dict_with_multiple_keys(self) -> None:
        """包含多个键的字典应该保留（去除 error_code 后）。"""
        detail, code = _normalize_detail(
            {
                "message": "x",
                "field": "name",
                "error_code": "validation",
            }
        )
        assert detail == {"message": "x", "field": "name"}
        assert code == "validation"


class TestResolveErrorCode:
    """测试 _resolve_error_code 函数。"""

    def test_returns_override_when_provided(self) -> None:
        """提供 override 时应该返回 override。"""
        assert _resolve_error_code(404, override="override_code") == "override_code"

    def test_returns_validation_error_for_422(self) -> None:
        """422 状态码应该返回 validation_error。"""
        assert _resolve_error_code(422) == "validation_error"

    def test_returns_mapped_code_for_known_status(self) -> None:
        """已知状态码应该返回对应的错误码。"""
        assert _resolve_error_code(404) == "not_found"
        assert _resolve_error_code(400) == "bad_request"
        assert _resolve_error_code(500) == "internal_error"

    def test_returns_unknown_error_for_unmapped_status(self) -> None:
        """未知状态码应该返回 unknown_error。"""
        assert _resolve_error_code(499) == "unknown_error"
        assert _resolve_error_code(418) == "unknown_error"


class TestDbContextFormatting:
    """测试数据库上下文格式化函数。"""

    def test_collect_db_metadata_for_valid_url(self) -> None:
        """有效的数据库 URL 应该正确解析。"""
        url = "postgresql+psycopg2://u:p@localhost:5432/ndr"
        meta = _collect_db_metadata(url)
        assert meta["db_driver"] == "postgresql+psycopg2"
        assert meta["db_username"] == "u"
        assert meta["db_host"] == "localhost"
        assert meta["db_port"] == 5432
        assert meta["db_name"] == "ndr"

    def test_collect_db_metadata_for_invalid_url(self) -> None:
        """无效的数据库 URL 应该返回默认值。"""
        url = "not-a-db-url"
        meta = _collect_db_metadata(url)
        assert meta == {"db_target": "<invalid>", "db_driver": "<unknown>"}

    def test_describe_db_target_for_valid_url(self) -> None:
        """有效的数据库 URL 应该生成可读的目标描述。"""
        url = "postgresql+psycopg2://u:p@localhost:5432/ndr"
        target = _describe_db_target(url)
        assert target == "postgresql+psycopg2://u@localhost:5432/ndr"

    def test_describe_db_target_for_invalid_url(self) -> None:
        """无效的数据库 URL 应该返回错误提示。"""
        url = "not-a-db-url"
        assert _describe_db_target(url) == "<invalid DB_URL>"

    def test_format_db_context_for_valid_url(self) -> None:
        """有效的数据库 URL 应该生成完整的上下文字符串。"""
        url = "postgresql+psycopg2://u:p@localhost:5432/ndr"
        ctx = _format_db_context(url)
        assert "db_driver=postgresql+psycopg2" in ctx
        assert "db_username=u" in ctx
        assert "db_host=localhost" in ctx
        assert "db_port=5432" in ctx
        assert "db_name=ndr" in ctx
        assert "db_target=" in ctx

    def test_format_db_context_for_invalid_url(self) -> None:
        """无效的数据库 URL 应该返回包含错误信息的上下文。"""
        url = "not-a-db-url"
        ctx = _format_db_context(url)
        assert "db_driver=<unknown>" in ctx
        assert "db_target=<invalid DB_URL>" in ctx
