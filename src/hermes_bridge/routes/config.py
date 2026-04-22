from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..cli import run_hermes_cli
from ..config import get_settings
from ..upstream import dashboard_request, filter_response_headers

router = APIRouter()
log = logging.getLogger("hermes_bridge.config")

# Debounced gateway restart: multiple rapid env/config edits coalesce into a
# single restart. Needed because the gateway process reads os.environ at
# startup only; changing /opt/data/.env does not propagate to its memory.
_GATEWAY_RELOAD_DELAY_S = 1.5
_gateway_reload_lock = asyncio.Lock()
_gateway_reload_task: asyncio.Task[None] | None = None


async def _do_gateway_reload(delay_s: float) -> None:
    try:
        await asyncio.sleep(delay_s)
        settings = get_settings()
        log.info("reloading gateway to pick up env/config changes")
        result = await run_hermes_cli(
            ["gateway", "restart"],
            container_name=settings.HERMES_CONTAINER_NAME,
            timeout=30.0,
        )
        if not result.ok:
            log.warning(
                "gateway reload failed rc=%s stderr=%s", result.returncode, result.stderr
            )
        else:
            log.info("gateway reloaded")
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("gateway reload task crashed")


async def _schedule_gateway_reload() -> None:
    """Debounced background restart of the gateway process."""
    global _gateway_reload_task
    async with _gateway_reload_lock:
        if _gateway_reload_task and not _gateway_reload_task.done():
            _gateway_reload_task.cancel()
        _gateway_reload_task = asyncio.create_task(
            _do_gateway_reload(_GATEWAY_RELOAD_DELAY_S)
        )


def _passthrough(resp: Any) -> Response:
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type"),
        headers=filter_response_headers(resp.headers),
    )


@router.get("/api/status")
async def status_proxy(request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "GET", "/api/status"))


@router.get("/api/gateway/reloading")
async def gateway_reloading() -> JSONResponse:
    """Returns whether a gateway reload is currently pending or running.

    The Flutter UI polls this after an env/config write so it can show a
    "reloading…" banner until the gateway is back and chats are safe to send.
    """
    task = _gateway_reload_task
    pending = bool(task and not task.done())
    return JSONResponse({"reloading": pending})


@router.get("/api/model/info")
async def model_info(request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "GET", "/api/model/info"))


@router.get("/api/providers/oauth")
async def providers_oauth(request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "GET", "/api/providers/oauth"))


@router.get("/api/tools/toolsets")
async def tools_toolsets(request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "GET", "/api/tools/toolsets"))


@router.get("/api/skills")
async def skills(request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "GET", "/api/skills"))


@router.put("/api/skills/toggle")
async def skills_toggle(request: Request) -> Response:
    body = await request.body()
    return _passthrough(
        await dashboard_request(
            request,
            "PUT",
            "/api/skills/toggle",
            content=body,
            extra_headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
    )


@router.get("/api/config")
async def get_config(request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "GET", "/api/config"))


@router.put("/api/config")
async def put_config(request: Request) -> Response:
    body = await request.body()
    resp = await dashboard_request(
        request,
        "PUT",
        "/api/config",
        content=body,
        extra_headers={"Content-Type": request.headers.get("content-type", "application/json")},
    )
    if 200 <= resp.status_code < 300:
        await _schedule_gateway_reload()
    return _passthrough(resp)


@router.get("/api/config/schema")
async def config_schema(request: Request) -> Response:
    cached = getattr(request.app.state, "config_schema", None)
    if cached is not None:
        return JSONResponse(cached)
    return _passthrough(await dashboard_request(request, "GET", "/api/config/schema"))


@router.get("/api/config/defaults")
async def config_defaults(request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "GET", "/api/config/defaults"))


@router.get("/api/env")
async def get_env(request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "GET", "/api/env"))


@router.put("/api/env")
async def put_env(request: Request) -> Response:
    body = await request.body()
    resp = await dashboard_request(
        request,
        "PUT",
        "/api/env",
        content=body,
        extra_headers={"Content-Type": request.headers.get("content-type", "application/json")},
    )
    if 200 <= resp.status_code < 300:
        await _schedule_gateway_reload()
    return _passthrough(resp)


@router.delete("/api/env")
async def delete_env(request: Request) -> Response:
    body = await request.body()
    resp = await dashboard_request(
        request,
        "DELETE",
        "/api/env",
        content=body if body else None,
        extra_headers={"Content-Type": request.headers.get("content-type", "application/json")}
        if body
        else None,
    )
    if 200 <= resp.status_code < 300:
        await _schedule_gateway_reload()
    return _passthrough(resp)


@router.post("/api/env/reveal")
async def reveal_env(request: Request) -> Response:
    body = await request.body()
    return _passthrough(
        await dashboard_request(
            request,
            "POST",
            "/api/env/reveal",
            content=body,
            extra_headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
    )
