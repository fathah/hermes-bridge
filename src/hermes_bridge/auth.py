from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .config import RateSpec, Settings

_MUTATION_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
_AUDIT_ROTATE_BYTES = 10 * 1024 * 1024


class SlidingWindowLimiter:
    """Per-key sliding window. Thread-safe via an asyncio.Lock."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str, spec: RateSpec, now: float) -> float | None:
        """Return None if allowed, else the Retry-After seconds value."""
        async with self._lock:
            window_start = now - spec.window_seconds
            hits = self._hits[key]
            while hits and hits[0] < window_start:
                hits.popleft()
            if len(hits) >= spec.limit:
                retry_after = max(1, int(spec.window_seconds - (now - hits[0])))
                return float(retry_after)
            hits.append(now)
            return None


class AuditLog:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()

    async def write(self, entry: dict[str, object]) -> None:
        async with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                if self._path.exists() and self._path.stat().st_size >= _AUDIT_ROTATE_BYTES:
                    rotated = self._path.with_suffix(self._path.suffix + ".1")
                    os.replace(self._path, rotated)
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
            except OSError:
                # Audit best-effort. Swallow so auth never fails because disk is full.
                pass


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer-token auth + per-IP sliding-window rate limit + audit log.

    `/health` is exempt from auth and rate limiting.
    """

    def __init__(
        self,
        app: ASGIApp,
        settings: Settings,
        limiter: SlidingWindowLimiter,
        audit: AuditLog,
    ) -> None:
        super().__init__(app)
        self._settings = settings
        self._limiter = limiter
        self._audit = audit

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if path == "/health" or path.startswith("/docs") or path.startswith("/openapi"):
            return await call_next(request)

        token = _extract_bearer(request)
        if not token or not hmac.compare_digest(token, self._settings.BRIDGE_TOKEN):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)

        method = request.method.upper()
        is_write = method in _MUTATION_METHODS
        spec = self._settings.write_rate if is_write else self._settings.read_rate
        client_ip = _client_ip(request)
        key = f"{client_ip}:{'w' if is_write else 'r'}"
        retry_after = await self._limiter.check(key, spec, time.monotonic())
        if retry_after is not None:
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(int(retry_after))},
            )

        response = await call_next(request)

        if is_write:
            await self._audit.write(
                {
                    "ts": time.time(),
                    "ip": client_ip,
                    "method": method,
                    "path": path,
                    "status": response.status_code,
                }
            )
        return response


def _extract_bearer(request: Request) -> str | None:
    raw = request.headers.get("authorization")
    if not raw:
        return None
    parts = raw.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"
