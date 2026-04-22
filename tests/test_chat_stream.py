from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from .conftest import HERMES_API_KEY, auth_headers


def test_chat_non_streaming_passthrough(client: TestClient, respx_router) -> None:
    respx_router.post("http://chat.test/v1/chat/completions").respond(
        200, json={"id": "cmpl-1", "choices": []}
    )
    resp = client.post(
        "/api/chat/completions",
        json={"model": "x", "messages": [], "stream": False},
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == "cmpl-1"


def test_chat_forwards_upstream_auth(client: TestClient, respx_router) -> None:
    captured: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={})

    respx_router.post("http://chat.test/v1/chat/completions").mock(side_effect=_capture)
    client.post(
        "/api/chat/completions",
        json={"model": "x", "messages": [], "stream": False},
        headers=auth_headers(),
    )
    assert captured["auth"] == f"Bearer {HERMES_API_KEY}"


def test_chat_streaming_yields_chunks_in_order(client: TestClient, respx_router) -> None:
    sse_bytes = (
        b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    respx_router.post("http://chat.test/v1/chat/completions").respond(
        200, content=sse_bytes, headers={"content-type": "text/event-stream"}
    )
    with client.stream(
        "POST",
        "/api/chat/completions",
        json={"model": "x", "messages": [], "stream": True},
        headers=auth_headers(),
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        buf = b"".join(resp.iter_bytes())
    assert buf == sse_bytes
