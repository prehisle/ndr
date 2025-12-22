import logging

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import OperationalError

from app.api.v1.deps import get_db, require_api_key
from app.api.v1.routers.admin import router as admin_router
from app.api.v1.routers.assets import router as assets_router
from app.api.v1.routers.documents import router as documents_router
from app.api.v1.routers.nodes import router as nodes_router
from app.api.v1.routers.relationships import router as relationships_router
from app.common.config import get_settings
from app.common.logging import setup_logging
from app.infra.db.alembic_support import get_head_revision, upgrade_to_head
from app.infra.db.session import get_engine
from app.infra.observability.metrics import metrics_app
from app.infra.observability.middleware import MetricsMiddleware

ERROR_CODE_BY_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    412: "precondition_failed",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "too_many_requests",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
}


def _normalize_detail(detail):
    if isinstance(detail, dict):
        maybe_code = detail.get("error_code")
        cleaned = {k: v for k, v in detail.items() if k != "error_code"}
        if len(cleaned) == 1 and "message" in cleaned:
            cleaned = cleaned["message"]
        if not cleaned:
            cleaned = None
        return cleaned, maybe_code if isinstance(maybe_code, str) else None
    return detail, None


def _resolve_error_code(status_code: int, override: str | None = None) -> str:
    if override:
        return override
    if status_code == 422:
        return "validation_error"
    return ERROR_CODE_BY_STATUS.get(status_code, "unknown_error")


def _collect_db_metadata(db_url: str) -> dict[str, object]:
    try:
        url = make_url(db_url)
    except Exception:
        return {"db_target": "<invalid>", "db_driver": "<unknown>"}

    payload: dict[str, object] = {"db_driver": url.drivername}
    if url.username:
        payload["db_username"] = url.username
    if url.host:
        payload["db_host"] = url.host
    if url.port:
        payload["db_port"] = url.port
    if url.database:
        payload["db_name"] = url.database
    return payload


def _describe_db_target(db_url: str) -> str:
    try:
        url = make_url(db_url)
    except Exception:
        return "<invalid DB_URL>"

    user = url.username or "?"
    host = url.host or "?"
    port = f":{url.port}" if url.port else ""
    database = f"/{url.database}" if url.database else ""
    return f"{url.drivername}://{user}@{host}{port}{database}"


def _format_db_context(db_url: str) -> str:
    meta = _collect_db_metadata(db_url)
    parts: list[str] = []
    for key in ("db_driver", "db_username", "db_host", "db_port", "db_name"):
        value = meta.get(key)
        if value is not None:
            parts.append(f"{key}={value}")
    target = _describe_db_target(db_url)
    if target:
        parts.append(f"db_target={target}")
    return ", ".join(parts)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging()
    app = FastAPI(
        title="NDR Service",
        version="v4.0",
        description="Documents & Nodes relationships service (MVP)",
    )

    # Optional CORS
    if settings.CORS_ENABLED:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS or ["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Routers
    app.include_router(
        documents_router,
        prefix="/api/v1",
        tags=["documents"],
        dependencies=[Depends(require_api_key)],
    )
    app.include_router(
        assets_router,
        prefix="/api/v1",
        tags=["assets"],
        dependencies=[Depends(require_api_key)],
    )
    app.include_router(
        nodes_router,
        prefix="/api/v1",
        tags=["nodes"],
        dependencies=[Depends(require_api_key)],
    )
    app.include_router(
        relationships_router,
        prefix="/api/v1",
        tags=["relationships"],
        dependencies=[Depends(require_api_key)],
    )
    app.include_router(
        admin_router,
        prefix="/api/v1",
        tags=["admin"],
    )

    # Metrics
    if settings.ENABLE_METRICS:
        app.add_middleware(MetricsMiddleware)
        app.mount("/metrics", metrics_app)

    @app.on_event("startup")
    def on_startup() -> None:
        startup_logger = logging.getLogger("app.startup")
        if settings.AUTO_APPLY_MIGRATIONS:
            db_context_text = _format_db_context(settings.DB_URL)
            startup_logger.info(
                "正在执行数据库迁移前的连接检查。[event=auto_migration_precheck] (%s)",
                db_context_text,
            )
            try:
                engine = get_engine()
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
            except OperationalError as exc:
                startup_logger.error(
                    "无法连接数据库，应用启动中断，请检查 DB_URL、账号密码或网络配置。"
                    " [event=auto_migration_connection_failed] (%s，error=%s)",
                    db_context_text,
                    exc,
                )
                raise
            startup_logger.info(
                "数据库连接检查通过，开始执行自动迁移。"
                " [event=auto_migration_begin] (%s)",
                db_context_text,
            )
            try:
                upgrade_to_head()
            except Exception as exc:
                startup_logger.exception(
                    "自动执行数据库迁移失败，请检查数据库权限与迁移脚本。"
                    " [event=auto_migration_failed] (%s，error=%s)",
                    db_context_text,
                    exc,
                )
                raise
            startup_logger.info(
                "数据库迁移完成，应用继续启动。"
                " [event=auto_migration_succeeded] (%s)",
                db_context_text,
            )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger = logging.getLogger("http")
        normalized_detail, code_override = _normalize_detail(exc.detail)
        logger.log(
            logging.WARNING if exc.status_code < 500 else logging.ERROR,
            "http_exception status=%s detail=%s method=%s path=%s request_id=%s user_id=%s",
            exc.status_code,
            normalized_detail,
            request.method,
            request.url.path,
            request.headers.get("X-Request-Id"),
            request.headers.get("X-User-Id") or "<missing>",
            extra={
                "extra": {
                    "status": exc.status_code,
                    "detail": normalized_detail,
                    "method": request.method,
                    "route": request.url.path,
                    "request_id": request.headers.get("X-Request-Id"),
                    "user_id": request.headers.get("X-User-Id") or "<missing>",
                }
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "HTTP Error",
                "status": exc.status_code,
                "detail": normalized_detail,
                "error_code": _resolve_error_code(exc.status_code, code_override),
                "instance": str(request.url),
                "request_id": request.headers.get("X-Request-Id"),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        return JSONResponse(
            status_code=422,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Validation Error",
                "status": 422,
                # 确保可序列化
                "detail": jsonable_encoder(exc.errors()),
                "error_code": _resolve_error_code(422),
                "instance": str(request.url),
                "request_id": request.headers.get("X-Request-Id"),
            },
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(db=Depends(get_db)):
        try:
            bind = db.get_bind()
            db.execute(text("SELECT 1"))
            inspector = inspect(bind)
            tables = set(inspector.get_table_names())
            required_tables = {
                "documents",
                "nodes",
                "node_documents",
                "assets",
                "node_assets",
                "idempotency_records",
            }
            missing = sorted(required_tables - tables)
            detail: dict[str, object] = {}
            if missing:
                detail["missing_tables"] = missing

            dialect = bind.dialect.name
            if dialect == "postgresql":
                head = get_head_revision()
                try:
                    current = db.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one_or_none()
                except Exception as exc:  # pragma: no cover - defensive path
                    detail["migrations"] = {
                        "status": "version_table_missing",
                        "expected": head,
                        "detail": str(exc),
                    }
                    current = None
                else:
                    if head and current != head:
                        detail["migrations"] = {
                            "status": "out_of_date",
                            "current": current,
                            "expected": head,
                        }
                ltree_enabled = db.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'ltree'")
                ).scalar_one_or_none()
                if not ltree_enabled:
                    detail["ltree_extension"] = "missing"

            if detail:
                return {"status": "not_ready", "detail": detail}
            return {"status": "ready"}
        except OperationalError as exc:
            return {"status": "not_ready", "detail": {"db": str(exc)}}
        except Exception as exc:  # pragma: no cover - defensive path
            return {"status": "not_ready", "detail": str(exc)}

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
