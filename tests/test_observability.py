from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infra.observability.middleware import MetricsMiddleware
from app.infra.observability.metrics import metrics_app


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/api/v1/nodes/{id}")
    def get_node(id: int):
        return {"id": id}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.mount("/metrics", metrics_app)
    return app


def test_metrics_route_template_label():
    app = build_app()
    client = TestClient(app)
    # trigger a request on a templated route
    resp = client.get("/api/v1/nodes/123")
    assert resp.status_code == 200

    # fetch metrics and assert low-cardinality route label is used
    m = client.get("/metrics")
    assert m.status_code == 200
    metrics_text = m.text
    assert "http_requests_total" in metrics_text
    assert 'route="/api/v1/nodes/{id}"' in metrics_text


def test_latency_metric_present():
    app = build_app()
    client = TestClient(app)
    client.get("/api/v1/nodes/456")
    m = client.get("/metrics")
    assert m.status_code == 200
    metrics_text = m.text
    assert "http_request_duration_seconds" in metrics_text
    assert 'route="/api/v1/nodes/{id}"' in metrics_text


def test_request_id_propagation():
    app = build_app()
    client = TestClient(app)

    # auto-generate when missing
    r1 = client.get("/health")
    rid1 = r1.headers.get("X-Request-Id")
    assert rid1 is not None and len(rid1) > 0

    # echo when provided
    rid = "req-abc-123"
    r2 = client.get("/health", headers={"X-Request-Id": rid})
    assert r2.headers.get("X-Request-Id") == rid