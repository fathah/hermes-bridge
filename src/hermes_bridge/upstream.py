from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import httpx
from fastapi import HTTPException, Request

from .config import Settings

if TYPE_CHECKING:
    from .dashboard_token import DashboardTokenManager


def build_clients(settings: Settings) -> tuple[httpx.AsyncClient, httpx.AsyncClient]:
    chat = httpx.AsyncClient(
        base_url=settings.HERMES_CHAT_URL,
        timeout=httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0),
    )
    dash = httpx.AsyncClient(
        base_url=settings.HERMES_DASH_URL,
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
    )
    return chat, dash


async def close_clients(*clients: httpx.AsyncClient) -> None:
    for c in clients:
        await c.aclose()


HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-encoding",
        "content-length",
    }
)


def filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in HOP_BY_HOP:
            continue
        out[k] = v
    return out


def forward_session_header(request: Request) -> dict[str, str]:
    sid = request.headers.get("x-hermes-session-id")
    return {"X-Hermes-Session-Id": sid} if sid else {}


async def dashboard_request(
    request: Request,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    json_body: object | None = None,
    content: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    client: httpx.AsyncClient = request.app.state.dash_client
    token_mgr = request.app.state.dashboard_token
    return await _do_dashboard_request(
        client,
        token_mgr,
        method,
        path,
        params=params,
        json_body=json_body,
        content=content,
        extra_headers=extra_headers,
    )


async def _do_dashboard_request(
    client: httpx.AsyncClient,
    token_mgr: DashboardTokenManager,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    json_body: object | None = None,
    content: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Proxy a call to hermes :9119 with the scraped ephemeral token.

    If the first call returns 401 (hermes restarted, token rotated),
    refresh the token and retry exactly once.
    """
    headers = dict(extra_headers or {})

    for attempt in (1, 2):
        token = await token_mgr.get()
        if token is None:
            raise HTTPException(
                status_code=503,
                detail="dashboard token unavailable; hermes :9119 unreachable",
            )
        headers["Authorization"] = f"Bearer {token}"
        resp = await client.request(
            method, path, params=params, json=json_body, content=content, headers=headers
        )
        if resp.status_code == 401 and attempt == 1:
            await token_mgr.refresh()
            continue
        return resp

    raise HTTPException(status_code=502, detail="dashboard auth retry exhausted")


async def iter_sse_chunks(resp: httpx.Response) -> AsyncIterator[bytes]:
    async for chunk in resp.aiter_bytes():
        yield chunk
