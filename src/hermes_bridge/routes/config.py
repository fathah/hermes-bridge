from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..upstream import dashboard_request, filter_response_headers

router = APIRouter()


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


@router.get("/api/model/info")
async def model_info(request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "GET", "/api/model/info"))


@router.get("/api/config")
async def get_config(request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "GET", "/api/config"))


@router.put("/api/config")
async def put_config(request: Request) -> Response:
    body = await request.body()
    return _passthrough(
        await dashboard_request(
            request,
            "PUT",
            "/api/config",
            content=body,
            extra_headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
    )


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
    return _passthrough(
        await dashboard_request(
            request,
            "PUT",
            "/api/env",
            content=body,
            extra_headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
    )


@router.delete("/api/env")
async def delete_env(request: Request) -> Response:
    body = await request.body()
    return _passthrough(
        await dashboard_request(
            request,
            "DELETE",
            "/api/env",
            content=body if body else None,
            extra_headers={"Content-Type": request.headers.get("content-type", "application/json")}
            if body
            else None,
        )
    )


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
