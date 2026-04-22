from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_all_up(client: TestClient, respx_router) -> None:
    respx_router.get("http://chat.test/health").respond(200, json={"status": "ok"})
    respx_router.get("http://dash.test/api/status").respond(200, json={"status": "ok"})
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["checks"]["hermes_chat"]["ok"] is True
    assert body["checks"]["hermes_dashboard"]["ok"] is True


def test_health_chat_down(client: TestClient, respx_router) -> None:
    respx_router.get("http://chat.test/health").respond(500, json={})
    respx_router.get("http://dash.test/api/status").respond(200, json={"status": "ok"})
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["checks"]["hermes_chat"]["ok"] is False
