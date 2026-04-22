from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from hermes_bridge.cli import CommandResult

from .conftest import auth_headers


def test_gateway_restart_success(client: TestClient) -> None:
    mock = AsyncMock(return_value=CommandResult(0, "restarted", ""))
    with patch("hermes_bridge.routes.gateway.run_hermes_cli", mock):
        resp = client.post("/api/gateway/restart", headers=auth_headers())
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock.assert_awaited_once()
        args, kwargs = mock.call_args
        assert args[0] == ["gateway", "restart"]
        assert kwargs["container_name"] == "hermes"


def test_gateway_stop_failure_propagates(client: TestClient) -> None:
    mock = AsyncMock(return_value=CommandResult(1, "", "boom"))
    with patch("hermes_bridge.routes.gateway.run_hermes_cli", mock):
        resp = client.post("/api/gateway/stop", headers=auth_headers())
        assert resp.status_code == 502
        assert resp.json()["detail"]["stderr"] == "boom"


def test_gateway_requires_auth(client: TestClient) -> None:
    assert client.post("/api/gateway/start").status_code == 401
