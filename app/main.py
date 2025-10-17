from fastapi import FastAPI
from fastapi import Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware

from app.common.config import get_settings
from app.common.logging import setup_logging
from app.api.v1.routers.documents import router as documents_router
from app.api.v1.routers.nodes import router as nodes_router
from app.api.v1.routers.relationships import router as relationships_router
from app.infra.observability.middleware import MetricsMiddleware
from app.infra.observability.metrics import metrics_app
from app.api.v1.deps import get_db, require_api_key
from sqlalchemy import text
from app.infra.db.base import Base
from app.infra.db.session import engine


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging()
    app = FastAPI(title="DMS Service", version="v4.0", description="Documents & Nodes relationships service (MVP)")

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
        documents_router, prefix="/api/v1", tags=["documents"], dependencies=[Depends(require_api_key)]
    )
    app.include_router(nodes_router, prefix="/api/v1", tags=["nodes"], dependencies=[Depends(require_api_key)])
    app.include_router(
        relationships_router, prefix="/api/v1", tags=["relationships"], dependencies=[Depends(require_api_key)]
    )

    # Metrics
    if settings.ENABLE_METRICS:
        app.add_middleware(MetricsMiddleware)
        app.mount("/metrics", metrics_app)

    @app.on_event("startup")
    def on_startup() -> None:
        # 开发态：自动创建表，便于快速起服务；生产改为 Alembic 迁移
        Base.metadata.create_all(bind=engine)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "HTTP Error",
                "status": exc.status_code,
                "detail": exc.detail,
                "instance": str(request.url),
                "request_id": request.headers.get("X-Request-Id"),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Validation Error",
                "status": 422,
                "detail": exc.errors(),
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
            db.execute(text("SELECT 1"))
            return {"status": "ready"}
        except Exception as e:
            return {"status": "not_ready", "detail": str(e)}

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)