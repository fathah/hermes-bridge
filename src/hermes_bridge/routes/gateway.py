from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ..cli import run_hermes_cli
from ..config import get_settings

router = APIRouter()


async def _lifecycle(action: str) -> JSONResponse:
    settings = get_settings()
    result = await run_hermes_cli(
        ["gateway", action],
        container_name=settings.HERMES_CONTAINER_NAME,
    )
    if not result.ok:
        raise HTTPException(
            status_code=502,
            detail={
                "action": action,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
    return JSONResponse(
        {"action": action, "ok": True, "stdout": result.stdout, "stderr": result.stderr}
    )


@router.post("/api/gateway/start")
async def gateway_start() -> JSONResponse:
    return await _lifecycle("start")


@router.post("/api/gateway/stop")
async def gateway_stop() -> JSONResponse:
    return await _lifecycle("stop")


@router.post("/api/gateway/restart")
async def gateway_restart() -> JSONResponse:
    return await _lifecycle("restart")
