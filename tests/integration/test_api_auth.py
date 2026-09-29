"""Tests for X-API-Key authentication on REST API routes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.config import get_settings


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def api_key() -> str:
    return get_settings().API_KEY


def test_healthz_no_auth_required(client: TestClient) -> None:
    """GET /healthz should not require API key (will fail on missing DB, but 503 not 401)."""
    resp = client.get("/healthz")
    assert resp.status_code != 401


def test_create_incident_missing_key_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/incidents",
        json={"title": "Test", "alert_text": "test alert", "services": ["svc"]},
    )
    assert resp.status_code == 401


def test_create_incident_wrong_key_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/incidents",
        json={"title": "Test", "alert_text": "test alert", "services": ["svc"]},
        headers={"X-API-Key": "wrong-key-12345"},
    )
    assert resp.status_code == 401


def test_get_incident_missing_key_returns_401(client: TestClient) -> None:
    resp = client.get("/incidents/INC-FAKE")
    assert resp.status_code == 401


def test_memory_search_missing_key_returns_401(client: TestClient) -> None:
    resp = client.get("/memory/search?q=pool+exhausted")
    assert resp.status_code == 401


def test_runbook_missing_key_returns_401(client: TestClient) -> None:
    resp = client.get("/runbooks/RB-db-pool-exhaustion")
    assert resp.status_code == 401


def test_resolve_missing_key_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/incidents/INC-FAKE/resolve",
        json={"root_cause": "test", "steps_taken": []},
    )
    assert resp.status_code == 401


def test_append_event_missing_key_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/incidents/INC-FAKE/events",
        json={"kind": "note", "content": "hello", "source": "human"},
    )
    assert resp.status_code == 401


def test_valid_key_accepted(client: TestClient, api_key: str) -> None:
    """With a valid key, auth passes — we get 404 (no Redis) or 500 (no Redis), never 401."""
    resp = client.get("/incidents/INC-DOES-NOT-EXIST", headers={"X-API-Key": api_key})
    assert resp.status_code != 401, f"Expected auth to pass, got 401: {resp.text}"
