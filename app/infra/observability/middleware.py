import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import iterate_in_threadpool

from app.common.config import get_settings
from app.infra.observability.metrics import LATENCY, REQUESTS


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        client = request.client or None
        client_ip = request.headers.get("X-Forwarded-For")
        if client_ip:
            client_ip = client_ip.split(",")[0].strip()
        elif client:
            client_ip = client.host
        else:
            client_ip = None

        trace_http = get_settings().TRACE_HTTP
        request_body: str | None = None
        if trace_http:
            try:
                raw_body = await request.body()
                if raw_body:
                    request_body = raw_body.decode("utf-8", errors="replace")
                    if len(request_body) > 2048:
                        request_body = request_body[:2048] + "...<truncated>"

                    async def receive():
                        return {
                            "type": "http.request",
                            "body": raw_body,
                            "more_body": False,
                        }

                    request._receive = receive  # type: ignore[attr-defined]
            except Exception:
                request_body = "<unavailable>"

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            elapsed = time.perf_counter() - start
            logger = logging.getLogger("http")
            user_id = request.headers.get("X-User-Id") or "<missing>"
            logger.exception(
                "request_error method=%s route=%s status=%s duration_ms=%.3f "
                "request_id=%s user_id=%s client_ip=%s query=%s user_agent=%s referer=%s",
                request.method,
                request.url.path,
                500,
                round(elapsed * 1000, 3),
                request_id,
                user_id,
                client_ip or "-",
                request.url.query or "-",
                request.headers.get("User-Agent") or "-",
                request.headers.get("Referer") or "-",
                extra={
                    "extra": {
                        "method": request.method,
                        "route": request.url.path,
                        "query": request.url.query,
                        "status": 500,
                        "duration_ms": round(elapsed * 1000, 3),
                        "request_id": request_id,
                        "user_id": user_id,
                        "client_ip": client_ip,
                        "user_agent": request.headers.get("User-Agent"),
                        "referer": request.headers.get("Referer"),
                        "exception": repr(exc),
                    }
                },
            )
            raise

        elapsed = time.perf_counter() - start

        route_template = request.scope.get("route", None)
        if route_template and hasattr(route_template, "path"):
            route = route_template.path
        else:
            route = request.url.path

        REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        LATENCY.labels(request.method, route).observe(elapsed)

        # ensure request-id propagation
        if "X-Request-Id" not in response.headers:
            response.headers["X-Request-Id"] = request_id

        # structured log with correlation id
        logger = logging.getLogger("http")
        user_header = request.headers.get("X-User-Id")
        user_id = user_header if user_header not in (None, "") else "<missing>"
        level = logging.INFO
        if status_code >= 500:
            level = logging.ERROR
        elif status_code >= 400:
            level = logging.WARNING

        duration_ms = round(elapsed * 1000, 3)
        message = (
            "request method=%s route=%s status=%s duration_ms=%.3f "
            "request_id=%s user_id=%s client_ip=%s query=%s user_agent=%s referer=%s"
        )
        response_body_str: str | None = None
        if trace_http:
            try:
                response_body_bytes = b""
                async for chunk in response.body_iterator:
                    response_body_bytes += chunk
                response.body_iterator = iterate_in_threadpool(
                    iter([response_body_bytes])
                )
                if response_body_bytes:
                    response_body_str = response_body_bytes.decode(
                        "utf-8", errors="replace"
                    )
                    if len(response_body_str) > 2048:
                        response_body_str = (
                            response_body_str[:2048] + "...<truncated>"
                        )
            except Exception:
                response_body_str = "<unavailable>"

        extra_payload = {
            "method": request.method,
            "route": route,
            "query": request.url.query,
            "status": status_code,
            "duration_ms": duration_ms,
            "request_id": request_id,
            "user_id": user_id,
            "client_ip": client_ip,
            "user_agent": request.headers.get("User-Agent"),
            "referer": request.headers.get("Referer"),
        }
        if trace_http:
            extra_payload["request_body"] = request_body
            extra_payload["response_body"] = response_body_str

        logger.log(
            level,  # type: ignore[arg-type]
            message,
            request.method,
            route,
            status_code,
            duration_ms,
            request_id,
            user_id,
            client_ip or "-",
            request.url.query or "-",
            request.headers.get("User-Agent") or "-",
            request.headers.get("Referer") or "-",
            extra={"extra": extra_payload},
        )
        return response
