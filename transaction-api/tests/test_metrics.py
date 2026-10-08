"""
Tests for the dedicated metrics-only app (app/metrics.py) and the
same-process-registry assumption run.py depends on: prometheus_client
Counters registered by app.main must be visible through metrics_app's own
/metrics response, since both apps are meant to run as two listeners of
the *same* process (see run.py docstring). If this ever broke (e.g.
someone accidentally imported a second, isolated prometheus_client
REGISTRY for metrics_app), the metrics port would silently report zero
forever regardless of real traffic on the main port -- this test exists
to catch exactly that.

Incrementing TRANSACTION_SAVE_SUCCESS_TOTAL directly (rather than through
POST /api/v1/transactions) keeps this test independent of a live
PostgreSQL connection -- see tests/test_health.py for DB-dependent
/readyz coverage instead.
"""
import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app.main import app as main_app, TRANSACTION_SAVE_SUCCESS_TOTAL
from app.metrics import metrics_app

metrics_client = TestClient(metrics_app)


def test_metrics_app_exposes_metrics_endpoint():
    r = metrics_client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_metrics_app_has_no_other_routes():
    r = metrics_client.get("/api/v1/transactions")
    assert r.status_code == 404
    r = metrics_client.get("/livez")
    assert r.status_code == 404


def test_metrics_app_shares_registry_with_main_app():
    before = TRANSACTION_SAVE_SUCCESS_TOTAL._value.get()

    TRANSACTION_SAVE_SUCCESS_TOTAL.inc()

    after = TRANSACTION_SAVE_SUCCESS_TOTAL._value.get()
    assert after == before + 1

    body = metrics_client.get("/metrics").text
    samples = {s.name: s.value for f in text_string_to_metric_families(body) for s in f.samples}
    assert samples["transaction_save_success_total"] == after
