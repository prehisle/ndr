from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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
