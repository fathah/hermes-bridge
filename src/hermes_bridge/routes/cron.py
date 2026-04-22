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


def _content_type(request: Request) -> dict[str, str]:
    return {"Content-Type": request.headers.get("content-type", "application/json")}


@router.get("/api/cron/jobs")
async def list_jobs(request: Request) -> Response:
    params = dict(request.query_params)
    return _passthrough(
        await dashboard_request(request, "GET", "/api/cron/jobs", params=params)
    )


@router.post("/api/cron/jobs")
async def create_job(request: Request) -> Response:
    body = await request.body()
    return _passthrough(
        await dashboard_request(
            request,
            "POST",
            "/api/cron/jobs",
            content=body,
            extra_headers=_content_type(request),
        )
    )


@router.put("/api/cron/jobs/{job_id}")
async def update_job(job_id: str, request: Request) -> Response:
    body = await request.body()
    return _passthrough(
        await dashboard_request(
            request,
            "PUT",
            f"/api/cron/jobs/{job_id}",
            content=body,
            extra_headers=_content_type(request),
        )
    )


@router.delete("/api/cron/jobs/{job_id}")
async def delete_job(job_id: str, request: Request) -> Response:
    return _passthrough(
        await dashboard_request(request, "DELETE", f"/api/cron/jobs/{job_id}")
    )


@router.post("/api/cron/jobs/{job_id}/pause")
async def pause_job(job_id: str, request: Request) -> Response:
    return _passthrough(
        await dashboard_request(request, "POST", f"/api/cron/jobs/{job_id}/pause")
    )


@router.post("/api/cron/jobs/{job_id}/resume")
async def resume_job(job_id: str, request: Request) -> Response:
    return _passthrough(
        await dashboard_request(request, "POST", f"/api/cron/jobs/{job_id}/resume")
    )


@router.post("/api/cron/jobs/{job_id}/trigger")
async def trigger_job(job_id: str, request: Request) -> Response:
    return _passthrough(
        await dashboard_request(request, "POST", f"/api/cron/jobs/{job_id}/trigger")
    )
