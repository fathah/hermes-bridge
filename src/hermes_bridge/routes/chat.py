from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from ..config import get_settings
from ..upstream import filter_response_headers, forward_session_header

router = APIRouter()


@router.post("/api/chat/completions")
async def chat_completions(request: Request) -> Response:
    body: dict[str, Any]
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

    settings = get_settings()
    client: httpx.AsyncClient = request.app.state.chat_client
    headers = {
        "Authorization": f"Bearer {settings.HERMES_API_KEY}",
        "Content-Type": "application/json",
        **forward_session_header(request),
    }

    if body.get("stream"):
        return await _stream_response(client, body, headers)

    upstream = await client.post("/v1/chat/completions", json=body, headers=headers)
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        headers=filter_response_headers(upstream.headers),
    )


async def _stream_response(
    client: httpx.AsyncClient,
    body: dict[str, Any],
    headers: dict[str, str],
) -> StreamingResponse:
    async def gen() -> AsyncIterator[bytes]:
        async with client.stream(
            "POST", "/v1/chat/completions", json=body, headers=headers
        ) as upstream:
            if upstream.status_code >= 400:
                payload = await upstream.aread()
                yield payload
                return
            async for chunk in upstream.aiter_bytes():
                yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
