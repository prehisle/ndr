import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app.api.v1.deps import get_db, require_api_key
from app.api.v1.routers.documents import router as documents_router
from app.api.v1.routers.nodes import router as nodes_router
from app.api.v1.routers.relationships import router as relationships_router
from app.common.config import get_settings
from app.common.logging import setup_logging
from app.infra.db.alembic_support import get_head_revision, upgrade_to_head
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


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging()
    app = FastAPI(
        title="DMS Service",
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

    # Metrics
    if settings.ENABLE_METRICS:
        app.add_middleware(MetricsMiddleware)
        app.mount("/metrics", metrics_app)

    @app.on_event("startup")
    def on_startup() -> None:
        if settings.AUTO_APPLY_MIGRATIONS:
            upgrade_to_head()

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        normalized_detail, code_override = _normalize_detail(exc.detail)
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
                "detail": exc.errors(),
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
