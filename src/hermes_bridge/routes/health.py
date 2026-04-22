from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    chat: httpx.AsyncClient = request.app.state.chat_client
    dash: httpx.AsyncClient = request.app.state.dash_client

    checks: dict[str, dict[str, object]] = {"bridge": {"ok": True}}

    checks["hermes_chat"] = await _probe(chat, "/health")
    checks["hermes_dashboard"] = await _probe(dash, "/api/status")

    required_ok = bool(checks["bridge"]["ok"]) and bool(checks["hermes_chat"]["ok"])
    all_ok = all(bool(v["ok"]) for v in checks.values())
    status = 200 if required_ok else 503
    return JSONResponse({"ok": all_ok, "checks": checks}, status_code=status)


async def _probe(client: httpx.AsyncClient, path: str) -> dict[str, object]:
    try:
        resp = await client.get(path, timeout=5.0)
    except httpx.HTTPError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": resp.status_code < 500, "status": resp.status_code}
