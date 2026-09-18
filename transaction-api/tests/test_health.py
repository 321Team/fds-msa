"""
Smoke / contract tests for transaction-api's health endpoints.

transaction-api needs DATABASE_URL set at import time (app/db.py reads
os.environ["DATABASE_URL"] when the module is imported) even though no
real database is used here. /readyz's DB check is mocked so this suite
runs without a live PostgreSQL instance.
"""
import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_livez_returns_ok_without_db():
    r = client.get("/livez")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_returns_ready_when_db_reachable():
    with patch("app.main.db_ping", new=AsyncMock(return_value=None)):
        r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


def test_readyz_returns_503_when_db_unreachable():
    with patch(
        "app.main.db_ping", new=AsyncMock(side_effect=ConnectionRefusedError())
    ):
        r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "not ready"}


def test_metrics_endpoint_is_exposed():
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_create_transaction_rejects_invalid_transaction_type():
    payload = {
        "account_id": "smoke-test-acct",
        "amount": 1000,
        "transaction_type": "not_a_real_type",
    }
    r = client.post("/api/v1/transactions", json=payload)
    assert r.status_code == 422  # pydantic validation failure -> nonzero contract
