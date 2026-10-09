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
"""
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app.main import app as main_app, FDS_EVALUATED_TOTAL
from app.metrics import metrics_app

main_client = TestClient(main_app)
metrics_client = TestClient(metrics_app)


def test_metrics_app_exposes_metrics_endpoint():
    r = metrics_client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_metrics_app_has_no_other_routes():
    r = metrics_client.get("/evaluate")
    assert r.status_code == 404
    r = metrics_client.get("/livez")
    assert r.status_code == 404


def test_metrics_app_shares_registry_with_main_app():
    # Increment via the main app (as a real scrape target would trigger),
    # then confirm the *metrics-only* app's own /metrics reflects it --
    # proving both read from the one process-global REGISTRY.
    before = FDS_EVALUATED_TOTAL._value.get()

    payload = {
        "transaction_id": "metrics-shared-registry-test",
        "account_id": "smoke-test-acct",
        "amount": 1000,
        "transaction_type": "deposit",
        "occurred_at": "2026-09-16T12:00:00+09:00",
        "received_at": "2026-09-16T12:00:00+09:00",
    }
    response = main_client.post("/evaluate", json=payload)
    assert response.status_code == 200

    after = FDS_EVALUATED_TOTAL._value.get()
    assert after == before + 1

    body = metrics_client.get("/metrics").text
    samples = {s.name: s.value for f in text_string_to_metric_families(body) for s in f.samples}
    assert samples["fds_evaluated_total"] == after
