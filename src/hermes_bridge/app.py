from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .auth import AuditLog, AuthMiddleware, SlidingWindowLimiter
from .config import Settings, get_settings
from .dashboard_token import DashboardTokenManager
from .routes import chat, cron, gateway, health, observability, providers, sessions
from .routes import config as config_routes
from .upstream import _do_dashboard_request, build_clients, close_clients

log = logging.getLogger("hermes_bridge")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.BRIDGE_LOG_LEVEL)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        chat_client, dash_client = build_clients(settings)
        app.state.chat_client = chat_client
        app.state.dash_client = dash_client
        app.state.dashboard_token = DashboardTokenManager(dash_client)
        app.state.config_schema = None

        # Warm caches best-effort; do not block startup on hermes availability.
        await app.state.dashboard_token.refresh()
        try:
            resp = await _do_dashboard_request(
                dash_client,
                app.state.dashboard_token,
                "GET",
                "/api/config/schema",
            )
            if resp.status_code == 200:
                app.state.config_schema = resp.json()
        except Exception as e:  # noqa: BLE001
            log.warning("config schema warm-up failed: %s", e)

        try:
            yield
        finally:
            await close_clients(chat_client, dash_client)

    app = FastAPI(
        title="hermes-bridge",
        version="0.1.0",
        description="Mobile-ready HTTP bridge for hermes-agent.",
        lifespan=lifespan,
    )

    limiter = SlidingWindowLimiter()
    audit = AuditLog(settings.BRIDGE_AUDIT_LOG_PATH)
    app.add_middleware(AuthMiddleware, settings=settings, limiter=limiter, audit=audit)

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(config_routes.router)
    app.include_router(providers.router)
    app.include_router(sessions.router)
    app.include_router(gateway.router)
    app.include_router(observability.router)
    app.include_router(cron.router)

    return app
