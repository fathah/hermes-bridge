from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import BRIDGE_TOKEN, auth_headers


def test_health_is_public(client: TestClient) -> None:
    # No auth header; should not 401 (status code will be 200/503 based on probes).
    resp = client.get("/health")
    assert resp.status_code in (200, 503)


def test_api_requires_bearer(client: TestClient) -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 401


def test_api_rejects_bad_bearer(client: TestClient) -> None:
    resp = client.get("/api/config", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_api_rejects_non_bearer_scheme(client: TestClient) -> None:
    resp = client.get("/api/config", headers={"Authorization": f"Basic {BRIDGE_TOKEN}"})
    assert resp.status_code == 401


def test_write_rate_limit(client: TestClient, respx_router) -> None:
    respx_router.put("http://dash.test/api/config").respond(200, json={"ok": True})
    for _ in range(5):
        r = client.put("/api/config", json={}, headers=auth_headers())
        assert r.status_code == 200
    r = client.put("/api/config", json={}, headers=auth_headers())
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_audit_log_written(client: TestClient, respx_router, tmp_path) -> None:
    respx_router.put("http://dash.test/api/config").respond(200, json={"ok": True})
    client.put("/api/config", json={"x": 1}, headers=auth_headers())
    audit = tmp_path / "audit.log"
    assert audit.exists()
    assert "/api/config" in audit.read_text()
