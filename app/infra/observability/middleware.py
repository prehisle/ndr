import logging
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from app.infra.observability.metrics import REQUESTS, LATENCY


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        route_template = request.scope.get("route", None)
        if route_template and hasattr(route_template, "path"):
            route = route_template.path
        else:
            route = request.url.path

        REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        LATENCY.labels(request.method, route).observe(elapsed)

        # ensure request-id propagation
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        if "X-Request-Id" not in response.headers:
            response.headers["X-Request-Id"] = request_id

        # structured log with correlation id
        logger = logging.getLogger("http")
        logger.info(
            "request",
            extra={
                "extra": {
                    "method": request.method,
                    "route": route,
                    "status": response.status_code,
                    "duration_ms": round(elapsed * 1000, 3),
                    "request_id": request_id,
                }
            },
        )
        return response