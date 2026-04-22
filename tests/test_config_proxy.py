from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from .conftest import auth_headers


def test_config_get_passthrough(client: TestClient, respx_router) -> None:
    respx_router.get("http://dash.test/api/config").respond(200, json={"foo": "bar"})
    resp = client.get("/api/config", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json() == {"foo": "bar"}


def test_config_injects_dashboard_bearer(client: TestClient, respx_router) -> None:
    captured: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={})

    respx_router.get("http://dash.test/api/config").mock(side_effect=_capture)
    client.get("/api/config", headers=auth_headers())
    assert captured["auth"] == "Bearer dashtok"


def test_dashboard_401_triggers_refresh_and_retry(client: TestClient, respx_router) -> None:
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(401, json={"detail": "token expired"})
        return httpx.Response(200, json={"after_refresh": True})

    # Second HTML scrape returns a rotated token.
    respx_router.get("http://dash.test/").respond(
        200, text='<script>window.__HERMES_SESSION_TOKEN__="rotated";</script>'
    )
    respx_router.get("http://dash.test/api/config").mock(side_effect=_handler)

    resp = client.get("/api/config", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json() == {"after_refresh": True}
    assert calls["n"] == 2


def test_put_config_forwards_body(client: TestClient, respx_router) -> None:
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    respx_router.put("http://dash.test/api/config").mock(side_effect=_capture)
    client.put(
        "/api/config",
        json={"model_name": "claude-opus-4-7"},
        headers=auth_headers(),
    )
    assert b"claude-opus-4-7" in captured["body"]  # type: ignore[operator]
