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


@router.get("/api/sessions")
async def list_sessions(request: Request) -> Response:
    params = dict(request.query_params)
    return _passthrough(await dashboard_request(request, "GET", "/api/sessions", params=params))


@router.get("/api/sessions/search")
async def search_sessions(request: Request) -> Response:
    params = dict(request.query_params)
    return _passthrough(
        await dashboard_request(request, "GET", "/api/sessions/search", params=params)
    )


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str, request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "GET", f"/api/sessions/{session_id}"))


@router.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, request: Request) -> Response:
    params = dict(request.query_params)
    return _passthrough(
        await dashboard_request(
            request, "GET", f"/api/sessions/{session_id}/messages", params=params
        )
    )


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, request: Request) -> Response:
    return _passthrough(await dashboard_request(request, "DELETE", f"/api/sessions/{session_id}"))
