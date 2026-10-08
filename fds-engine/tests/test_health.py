"""
Smoke / contract tests for fds-engine's HTTP surface.

fds-engine has no external dependencies (no DB), so these run against the
real FastAPI app with no mocking required.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_livez_returns_ok():
    r = client.get("/livez")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_returns_ok():
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_metrics_is_not_served_on_business_port():
    # 메트릭은 전용 listener(app.metrics.metrics_app)만 응답한다(tests/test_metrics.py).
    r = client.get("/metrics")
    assert r.status_code == 404


def test_evaluate_contract_happy_path():
    payload = {
        "transaction_id": "smoke-test-tx-1",
        "account_id": "smoke-test-acct",
        "amount": 5_000_000,
        "currency": "KRW",
        "transaction_type": "withdrawal",
        "source_ip": "127.0.0.1",
        "occurred_at": "2026-09-16T12:00:00+09:00",
        "received_at": "2026-09-16T12:00:00+09:00",
        "context": {"recent_withdrawal_count_10m": 3},
    }
    r = client.post("/evaluate", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["transaction_id"] == "smoke-test-tx-1"
    assert body["fds_detected"] is True
    assert {rule["rule_id"] for rule in body["fds_rules"]} == {"R01", "R02", "R04", "R07"}


def test_evaluate_rejects_invalid_transaction_type():
    payload = {
        "transaction_id": "smoke-test-tx-2",
        "account_id": "smoke-test-acct",
        "amount": 1000,
        "transaction_type": "not_a_real_type",
        "occurred_at": "2026-09-16T12:00:00+09:00",
        "received_at": "2026-09-16T12:00:00+09:00",
    }
    r = client.post("/evaluate", json=payload)
    assert r.status_code == 422  # FastAPI/pydantic validation failure -> nonzero contract
