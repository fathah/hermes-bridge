from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from ..config import get_settings
from ..upstream import filter_response_headers, forward_session_header

log = logging.getLogger("hermes_bridge.chat")

router = APIRouter()

EMPTY_RESPONSE_NOTICE = (
    "⚠️ The model returned an empty response.\n\n"
    "This usually means the upstream provider rejected the request — common causes:\n"
    "• The selected model isn't available to your provider account "
    "(e.g. OpenRouter provider preferences blocking it)\n"
    "• The provider returned an error hermes silently swallowed\n"
    "• Free-tier rate limit / temporary upstream outage\n\n"
    "Check `docker logs hermes` and your provider account settings."
)


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

    content = upstream.content
    if upstream.status_code == 200 and "json" in (upstream.headers.get("content-type") or ""):
        try:
            payload = json.loads(content.decode())
        except (ValueError, UnicodeDecodeError):
            payload = None
        if isinstance(payload, dict):
            choices = payload.get("choices") or []
            first_msg = (choices[0].get("message") or {}) if choices and isinstance(choices[0], dict) else {}
            text = first_msg.get("content") or ""
            reasoning = first_msg.get("reasoning_content") or first_msg.get("reasoning") or ""
            if not text and not reasoning:
                first_msg["content"] = EMPTY_RESPONSE_NOTICE
                if choices and isinstance(choices[0], dict):
                    choices[0]["message"] = first_msg
                payload["choices"] = choices
                content = json.dumps(payload).encode()
                log.warning("chat ◀ injected empty-response diagnostic into non-stream body")

    return Response(
        content=content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        headers=filter_response_headers(upstream.headers),
    )


def _build_diagnostic_chunk(model: str | None) -> bytes:
    chunk = {
        "id": f"chatcmpl-bridge-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model or "hermes-agent",
        "choices": [
            {"index": 0, "delta": {"content": EMPTY_RESPONSE_NOTICE}, "finish_reason": None}
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n".encode()


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
            content_chars = 0
            reasoning_chars = 0
            completion_tokens: int | None = None
            response_model: str | None = None
            first_preview: bytes | None = None
            buffer = b""

            async for chunk in upstream.aiter_bytes():
                chunks += 1
                total += len(chunk)
                if first_preview is None:
                    first_preview = chunk[:200]
                    log.info("chat ◀ first chunk bytes=%d preview=%r", len(chunk), first_preview)

                buffer += chunk
                # SSE frames end with \n\n. Process complete frames; buffer the tail.
                while b"\n\n" in buffer:
                    frame, buffer = buffer.split(b"\n\n", 1)
                    frame_with_sep = frame + b"\n\n"

                    stripped = frame.strip()

                    # Intercept terminator — inject diagnostic if no content was streamed.
                    if stripped == b"data: [DONE]":
                        if content_chars == 0 and reasoning_chars == 0:
                            yield _build_diagnostic_chunk(response_model)
                            log.warning(
                                "chat ◀ injected empty-response diagnostic "
                                "(completion_tokens=%s)",
                                completion_tokens,
                            )
                        yield frame_with_sep
                        continue

                    # Track delta sizes + usage by parsing data: {...} payloads.
                    if stripped.startswith(b"data:"):
                        try:
                            payload = json.loads(stripped[5:].strip())
                        except (ValueError, json.JSONDecodeError):
                            payload = None
                        if isinstance(payload, dict):
                            if response_model is None:
                                m = payload.get("model")
                                if isinstance(m, str):
                                    response_model = m
                            choices = payload.get("choices") or []
                            if choices and isinstance(choices[0], dict):
                                delta = choices[0].get("delta") or {}
                                content = delta.get("content")
                                if isinstance(content, str):
                                    content_chars += len(content)
                                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                                if isinstance(reasoning, str):
                                    reasoning_chars += len(reasoning)
                            usage = payload.get("usage")
                            if isinstance(usage, dict):
                                ct = usage.get("completion_tokens")
                                if isinstance(ct, int):
                                    completion_tokens = ct

                    yield frame_with_sep

            # Flush any tail (no trailing \n\n). If upstream never sent [DONE]
            # but produced no content, still inject so the user sees something.
            if buffer:
                yield buffer
            elif content_chars == 0 and reasoning_chars == 0 and chunks == 0:
                # No upstream output at all — synthesize a minimal stream.
                yield _build_diagnostic_chunk(response_model)
                yield b"data: [DONE]\n\n"
                log.warning("chat ◀ upstream emitted nothing; sent synthetic stream")

            log.info(
                "chat ◀ stream done chunks=%d total_bytes=%d content_chars=%d "
                "reasoning_chars=%d completion_tokens=%s",
                chunks,
                total,
                content_chars,
                reasoning_chars,
                completion_tokens,
            )

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
