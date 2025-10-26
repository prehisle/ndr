import json
import logging
import time
import uuid
from typing import Any

from fastapi import Request
from starlette.concurrency import iterate_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from app.common.config import get_settings
from app.infra.observability.metrics import LATENCY, REQUESTS


class MetricsMiddleware(BaseHTTPMiddleware):
    SENSITIVE_KEYS = {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "x-api-key",
        "authorization",
    }

    def _mask_mapping(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            masked: dict[str, Any] = {}
            for k, v in obj.items():
                if isinstance(k, str) and k.lower() in self.SENSITIVE_KEYS:
                    masked[k] = "***"
                else:
                    masked[k] = self._mask_mapping(v)
            return masked
        if isinstance(obj, list):
            return [self._mask_mapping(x) for x in obj]
        return obj

    def _mask_text(self, text: str) -> str:
        # 简单文本掩码：对形如 token=xxxx 或 Authorization: Bearer xxxx 的片段进行模糊替换
        try:
            import re

            patterns = [
                r"(?i)(token|secret|api_key|x-api-key|password|authorization)\s*[:=]\s*[^\s]+",
                r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9\-_.]+",
            ]
            masked = text
            for p in patterns:
                masked = re.sub(
                    p,
                    lambda m: m.group(0).split(":")[0].split("=")[0] + ": ***",
                    masked,
                )
            return masked
        except Exception:
            return text

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
                    decoded_body = raw_body.decode("utf-8", errors="replace")
                    # JSON 尝试脱敏，否则进行基于文本的简易脱敏
                    try:
                        parsed = json.loads(decoded_body)
                    except Exception:
                        masked_text = self._mask_text(decoded_body)
                        if len(masked_text) > 2048:
                            masked_text = masked_text[:2048] + "...<truncated>"
                        request_body = masked_text
                    else:
                        masked_obj = self._mask_mapping(parsed)
                        masked_text = json.dumps(masked_obj, ensure_ascii=False)
                        if len(masked_text) > 2048:
                            masked_text = masked_text[:2048] + "...<truncated>"
                        request_body = masked_text

                    async def receive():
                        return {
                            "type": "http.request",
                            "body": raw_body,
                            "more_body": False,
                        }

                    request._receive = receive
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
        user_id = user_header or "<missing>"
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
                    decoded_body = response_body_bytes.decode("utf-8", errors="replace")
                    # JSON 尝试脱敏
                    try:
                        parsed = json.loads(decoded_body)
                    except Exception:
                        masked_text = self._mask_text(decoded_body)
                        if len(masked_text) > 2048:
                            masked_text = masked_text[:2048] + "...<truncated>"
                        response_body_str = masked_text
                    else:
                        masked_obj = self._mask_mapping(parsed)
                        masked_text = json.dumps(masked_obj, ensure_ascii=False)
                        if len(masked_text) > 2048:
                            masked_text = masked_text[:2048] + "...<truncated>"
                        response_body_str = masked_text
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
            level,
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
