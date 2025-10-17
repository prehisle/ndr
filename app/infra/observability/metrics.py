from prometheus_client import Counter, Histogram, make_asgi_app

# 低基数标签：使用路由模板（如 /api/v1/nodes/{id}），避免动态 ID 导致高基数
REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
)

LATENCY = Histogram(
    "http_request_duration_seconds",
    "Request latency in seconds",
    ["method", "route"],
)

# /metrics 端点 ASGI 应用
metrics_app = make_asgi_app()