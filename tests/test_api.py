"""Tests for top-level FastAPI app behavior and the remaining CRUD routers."""

from __future__ import annotations


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "environment" in body


def test_openapi_schema_is_served(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Prompt Eval Harness"


def test_unknown_route_returns_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404


def test_model_config_crud_round_trip(client):
    create_response = client.post(
        "/api/model-configs",
        json={
            "name": "gpt-4o-mini-default",
            "provider": "openai",
            "model_id": "gpt-4o-mini",
            "temperature": 0.2,
            "max_tokens": 512,
        },
    )
    assert create_response.status_code == 201
    config_id = create_response.json()["id"]

    get_response = client.get(f"/api/model-configs/{config_id}")
    assert get_response.status_code == 200
    assert get_response.json()["provider"] == "openai"

    delete_response = client.delete(f"/api/model-configs/{config_id}")
    assert delete_response.status_code == 204
    assert client.get(f"/api/model-configs/{config_id}").status_code == 404


def test_model_config_rejects_duplicate_name(client):
    payload = {
        "name": "dupe",
        "provider": "anthropic",
        "model_id": "claude-sonnet-5",
    }
    client.post("/api/model-configs", json=payload)
    response = client.post("/api/model-configs", json=payload)
    assert response.status_code == 409


def test_test_suite_and_case_round_trip(client):
    suite = client.post("/api/test-suites", json={"name": "geo-suite"}).json()
    case_response = client.post(
        f"/api/test-suites/{suite['id']}/test-cases",
        json={
            "name": "capital-of-france",
            "input_variables": {"question": "What is the capital of France?"},
            "expected_output": "Paris",
            "evaluation_method": "exact_match",
        },
    )
    assert case_response.status_code == 201

    cases = client.get(f"/api/test-suites/{suite['id']}/test-cases").json()
    assert len(cases) == 1
    assert cases[0]["expected_output"] == "Paris"


def test_delete_test_suite_cascades_to_cases(client):
    suite = client.post("/api/test-suites", json={"name": "cascade-suite"}).json()
    client.post(
        f"/api/test-suites/{suite['id']}/test-cases",
        json={"name": "case-1", "input_variables": {}, "evaluation_method": "exact_match"},
    )

    response = client.delete(f"/api/test-suites/{suite['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/test-suites/{suite['id']}").status_code == 404
