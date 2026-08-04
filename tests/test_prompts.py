"""Tests for prompt CRUD and version-history endpoints."""

from __future__ import annotations


def test_create_prompt_returns_first_version(client):
    response = client.post(
        "/api/prompts",
        json={"name": "greeting", "description": "A friendly greeting", "template": "Hello, {{ name }}!"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "greeting"
    assert len(body["versions"]) == 1
    assert body["versions"][0]["version_number"] == 1
    assert body["versions"][0]["variables"] == ["name"]


def test_create_prompt_rejects_duplicate_name(client):
    payload = {"name": "greeting", "template": "Hi {{ name }}"}
    client.post("/api/prompts", json=payload)
    response = client.post("/api/prompts", json=payload)
    assert response.status_code == 409


def test_create_prompt_rejects_invalid_template(client):
    response = client.post("/api/prompts", json={"name": "broken", "template": "{% if %}"})
    assert response.status_code == 400


def test_list_prompts(client):
    client.post("/api/prompts", json={"name": "a", "template": "A"})
    client.post("/api/prompts", json={"name": "b", "template": "B"})
    response = client.get("/api/prompts")
    assert response.status_code == 200
    names = {p["name"] for p in response.json()}
    assert names == {"a", "b"}


def test_get_prompt_404_for_unknown_id(client):
    response = client.get("/api/prompts/does-not-exist")
    assert response.status_code == 404


def test_create_and_list_prompt_versions(client):
    created = client.post("/api/prompts", json={"name": "iter", "template": "v1 {{ x }}"}).json()
    prompt_id = created["id"]

    response = client.post(
        f"/api/prompts/{prompt_id}/versions",
        json={"template": "v2 {{ x }} {{ y }}", "commit_message": "add y"},
    )
    assert response.status_code == 201
    assert response.json()["version_number"] == 2
    assert response.json()["variables"] == ["x", "y"]

    versions = client.get(f"/api/prompts/{prompt_id}/versions").json()
    assert [v["version_number"] for v in versions] == [1, 2]


def test_diff_prompt_versions(client):
    created = client.post("/api/prompts", json={"name": "diffme", "template": "line one"}).json()
    prompt_id = created["id"]
    client.post(f"/api/prompts/{prompt_id}/versions", json={"template": "line two"})

    response = client.get(f"/api/prompts/{prompt_id}/diff", params={"from_version": 1, "to_version": 2})
    assert response.status_code == 200
    diff = response.json()["diff"]
    assert "-line one" in diff
    assert "+line two" in diff


def test_diff_prompt_versions_404_for_unknown_version(client):
    created = client.post("/api/prompts", json={"name": "onlyone", "template": "hi"}).json()
    prompt_id = created["id"]

    response = client.get(f"/api/prompts/{prompt_id}/diff", params={"from_version": 1, "to_version": 2})
    assert response.status_code == 404


def test_delete_prompt(client):
    created = client.post("/api/prompts", json={"name": "temp", "template": "bye"}).json()
    prompt_id = created["id"]

    response = client.delete(f"/api/prompts/{prompt_id}")
    assert response.status_code == 204
    assert client.get(f"/api/prompts/{prompt_id}").status_code == 404
