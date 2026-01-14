from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.testclient import TestClient

from app.common.config import get_settings
from app.infra.observability.middleware import MetricsMiddleware


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.post("/echo")
    async def echo(request: Request):
        body = await request.json()
        # 回传一个包含敏感字段的响应
        return JSONResponse(
            {"ok": True, "token": body.get("token"), "password": body.get("password")}
        )

    return app


def test_trace_masking_masks_sensitive_fields(caplog, monkeypatch):
    monkeypatch.setenv("TRACE_HTTP", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = build_app()
    client = TestClient(app)

    with caplog.at_level("INFO"):
        r = client.post(
            "/echo", json={"user": "u", "password": "p@ss", "token": "abc123"}
        )
        assert r.status_code == 200

    # 找到 http 结构化日志，直接读取 LogRecord.extra（由中间件注入）
    records = [
        rec
        for rec in caplog.records
        if rec.name == "http" and "request" in rec.getMessage()
    ]
    assert records, "should capture http logs"
    rec = records[-1]
    # 结构化字段挂载在 record.extra 上
    assert hasattr(rec, "extra") and isinstance(rec.extra, dict)
    assert "request_body" in rec.extra
    assert "response_body" in rec.extra
    assert "***" in (rec.extra.get("request_body") or "")
    assert "***" in (rec.extra.get("response_body") or "")


def test_trace_masking_masks_plain_text_and_truncates(caplog, monkeypatch):
    """测试纯文本请求/响应的掩码和截断功能。"""
    monkeypatch.setenv("TRACE_HTTP", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.post("/plain")
    async def plain(request: Request):
        # 消费 body
        _ = await request.body()
        # 构造超长纯文本，触发截断逻辑
        long_text = ("token=abc password=def " * 200).strip()
        return PlainTextResponse(long_text)

    client = TestClient(app)
    # 发送超长纯文本请求
    payload = ("token=abc password=def " * 200).strip()
    headers = {"X-Forwarded-For": "1.1.1.1, 2.2.2.2"}

    with caplog.at_level("INFO"):
        r = client.post("/plain", data=payload, headers=headers)
        assert r.status_code == 200

    records = [
        rec
        for rec in caplog.records
        if rec.name == "http" and "request" in rec.getMessage()
    ]
    assert records, "should capture http logs"
    rec = records[-1]
    assert hasattr(rec, "extra") and isinstance(rec.extra, dict)

    # 验证 client_ip 从 X-Forwarded-For 解析
    assert rec.extra.get("client_ip") == "1.1.1.1"
    # 验证敏感字段被掩码
    assert "***" in (rec.extra.get("request_body") or "")
    # 验证截断
    request_body = rec.extra.get("request_body") or ""
    if len(request_body) > 100:
        assert request_body.endswith("...<truncated>")


def test_middleware_logs_downstream_exception(caplog, monkeypatch):
    """测试下游抛出异常时的日志记录。"""
    monkeypatch.setenv("TRACE_HTTP", "false")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level("ERROR"):
        r = client.get("/boom", headers={"X-User-Id": "u"})
        assert r.status_code == 500

    records = [
        rec
        for rec in caplog.records
        if rec.name == "http" and "request_error" in rec.getMessage()
    ]
    assert records, "should capture request_error logs"
    rec = records[-1]
    assert hasattr(rec, "extra") and isinstance(rec.extra, dict)
    assert rec.extra.get("status") == 500
    assert "RuntimeError" in (rec.extra.get("exception") or "")
