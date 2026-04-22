from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

BRIDGE_TOKEN = "t" * 40
HERMES_API_KEY = "h" * 40


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BRIDGE_TOKEN", BRIDGE_TOKEN)
    monkeypatch.setenv("HERMES_API_KEY", HERMES_API_KEY)
    monkeypatch.setenv("HERMES_CHAT_URL", "http://chat.test")
    monkeypatch.setenv("HERMES_DASH_URL", "http://dash.test")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("BRIDGE_AUDIT_LOG_PATH", str(tmp_path / "audit.log"))
    monkeypatch.setenv("BRIDGE_RATE_WRITE", "5/10s")
    monkeypatch.setenv("BRIDGE_RATE_READ", "20/10s")
    from hermes_bridge import config as cfg

    cfg.reset_settings_for_tests()


@pytest.fixture
def respx_router() -> Iterator[respx.Router]:
    # Mock every httpx.AsyncClient globally; startup scrape will hit this.
    with respx.mock(assert_all_called=False, assert_all_mocked=False) as r:
        # Default successful scrape + schema warm-up so lifespan doesn't error.
        r.get("http://dash.test/").respond(
            200, text='<html><script>window.__HERMES_SESSION_TOKEN__="dashtok";</script></html>'
        )
        r.get("http://dash.test/api/config/schema").respond(200, json={"ok": True})
        yield r


@pytest.fixture
def app(respx_router: respx.Router) -> FastAPI:
    from hermes_bridge.app import create_app

    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {BRIDGE_TOKEN}"}
