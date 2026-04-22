from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from ..config import get_settings
from ..upstream import filter_response_headers, forward_session_header

log = logging.getLogger("hermes_bridge.chat")

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

    messages = body.get("messages") or []
    last = messages[-1] if messages else {}
    last_preview = str(last.get("content"))[:120] if isinstance(last, dict) else ""
    log.info(
        "chat ▶ model=%s stream=%s msgs=%d session=%s last=%r",
        body.get("model"),
        bool(body.get("stream")),
        len(messages),
        request.headers.get("x-hermes-session-id"),
        last_preview,
    )

    if body.get("stream"):
        return await _stream_response(client, body, headers)

    upstream = await client.post("/v1/chat/completions", json=body, headers=headers)
    log.info(
        "chat ◀ non-stream status=%d bytes=%d ct=%s body=%r",
        upstream.status_code,
        len(upstream.content),
        upstream.headers.get("content-type"),
        upstream.content[:500],
    )
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
            log.info(
                "chat ◀ stream open status=%d ct=%s",
                upstream.status_code,
                upstream.headers.get("content-type"),
            )
            if upstream.status_code >= 400:
                payload = await upstream.aread()
                log.warning("chat ◀ stream error body=%r", payload[:500])
                yield payload
                return
            chunks = 0
            total = 0
            first_preview: bytes | None = None
            async for chunk in upstream.aiter_bytes():
                chunks += 1
                total += len(chunk)
                if first_preview is None:
                    first_preview = chunk[:200]
                    log.info("chat ◀ first chunk bytes=%d preview=%r", len(chunk), first_preview)
                yield chunk
            log.info("chat ◀ stream done chunks=%d total_bytes=%d", chunks, total)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
