from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..upstream import dashboard_request, filter_response_headers

router = APIRouter()


def _passthrough(resp: object) -> Response:
    return Response(
        content=resp.content,  # type: ignore[attr-defined]
        status_code=resp.status_code,  # type: ignore[attr-defined]
        media_type=resp.headers.get("content-type"),  # type: ignore[attr-defined]
        headers=filter_response_headers(resp.headers),  # type: ignore[attr-defined]
    )


@router.get("/api/logs")
async def get_logs(request: Request) -> Response:
    params = dict(request.query_params)
    return _passthrough(await dashboard_request(request, "GET", "/api/logs", params=params))


@router.get("/api/analytics/usage")
async def analytics_usage(request: Request) -> Response:
    params = dict(request.query_params)
    return _passthrough(
        await dashboard_request(request, "GET", "/api/analytics/usage", params=params)
    )
