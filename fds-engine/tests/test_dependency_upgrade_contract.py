"""JSON/OpenAPI regression checks; no external services or deployment."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_openapi_preserves_evaluate_json_schema():
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    operation = schema["paths"]["/evaluate"]["post"]
    assert "application/json" in operation["requestBody"]["content"]
    assert {"200", "422"} <= operation["responses"].keys()
    required = schema["components"]["schemas"]["EvaluateRequest"]["required"]
    assert set(required) == {"transaction_id", "account_id", "amount", "transaction_type",
                             "occurred_at", "received_at"}


def test_malformed_json_rejected_before_rule_evaluation():
    with patch("app.main.evaluate_all") as evaluate, TestClient(app) as client:
        response = client.post("/evaluate", content='{"transaction_id":',
                               headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    evaluate.assert_not_called()
