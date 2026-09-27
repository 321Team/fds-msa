"""HTTP compatibility checks for the dependency upgrade; DB/engine are mocked.

These preserve observed source behavior, not approval of the draft business
contract. No real PostgreSQL, engine service, or cluster is contacted.
"""
import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


def payload():
    return {"account_id": "dependency-test", "amount": 1000, "transaction_type": "deposit"}


def session_context(session):
    context = AsyncMock()
    context.__aenter__.return_value = session
    return context


def test_openapi_preserves_transaction_json_schema():
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    operation = schema["paths"]["/api/v1/transactions"]["post"]
    assert "application/json" in operation["requestBody"]["content"]
    assert {"201", "422"} <= operation["responses"].keys()
    request = schema["components"]["schemas"]["TransactionRequest"]
    assert set(request["required"]) == {"account_id", "amount", "transaction_type"}
    assert request["properties"]["transaction_type"]["pattern"] == "^(withdrawal|transfer|deposit)$"


def test_transaction_json_response_and_mock_commit():
    session = AsyncMock()
    evaluated = {"fds_detected": False, "fds_rules": []}
    with patch("app.main.async_session", return_value=session_context(session)), \
         patch("app.main.build_context", new=AsyncMock(return_value={})), \
         patch("app.main.call_fds_engine", new=AsyncMock(return_value=evaluated)), \
         TestClient(app) as client:
        response = client.post("/api/v1/transactions", json=payload())
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"transaction_id", "fds_detected", "fds_rules", "fds_evaluation_skipped"}
    assert body["fds_detected"] is False and body["fds_rules"] == []
    assert body["fds_evaluation_skipped"] is False
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_engine_timeout_preserves_existing_fail_open_response():
    session = AsyncMock()
    upstream = AsyncMock()
    upstream.post.side_effect = httpx.ReadTimeout("fixture timeout")
    with patch("app.main.async_session", return_value=session_context(session)), \
         patch("app.main.build_context", new=AsyncMock(return_value={})), \
         patch("app.fds_client.httpx.AsyncClient", return_value=session_context(upstream)), \
         TestClient(app) as client:
        response = client.post("/api/v1/transactions", json=payload())
    assert response.status_code == 201
    body = response.json()
    assert body["fds_detected"] is None and body["fds_rules"] is None
    assert body["fds_evaluation_skipped"] is True
    upstream.post.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_mock_database_write_failure_returns_500_and_rolls_back():
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("fixture database failure")
    with patch("app.main.async_session", return_value=session_context(session)), \
         patch("app.main.build_context", new=AsyncMock(return_value={})), \
         patch("app.main.call_fds_engine", new=AsyncMock(return_value=None)), \
         TestClient(app) as client:
        response = client.post("/api/v1/transactions", json=payload())
    assert response.status_code == 500
    assert response.json() == {"detail": "transaction save failed"}
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("body", ['{"account_id":', '{}'])
def test_invalid_json_rejected_before_database_access(body):
    with patch("app.main.async_session") as factory, TestClient(app) as client:
        response = client.post("/api/v1/transactions", content=body,
                               headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    factory.assert_not_called()
