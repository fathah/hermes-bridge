from __future__ import annotations

import asyncio
import logging
import re

import httpx

_HTML_TOKEN_RE = re.compile(r'window\.__HERMES_SESSION_TOKEN__\s*=\s*"([^"]+)"')

log = logging.getLogger(__name__)


class DashboardTokenManager:
    """Scrapes and caches hermes' ephemeral dashboard token (see PLAN §7)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> str | None:
        if self._token is None:
            await self.refresh()
        return self._token

    async def refresh(self) -> str | None:
        async with self._lock:
            try:
                resp = await self._client.get("/")
            except httpx.HTTPError as e:
                log.warning("dashboard token scrape failed: %s", e)
                self._token = None
                return None
            if resp.status_code != 200:
                log.warning("dashboard / returned %s", resp.status_code)
                self._token = None
                return None
            m = _HTML_TOKEN_RE.search(resp.text)
            if not m:
                log.warning("dashboard HTML missing __HERMES_SESSION_TOKEN__")
                self._token = None
                return None
            self._token = m.group(1)
            return self._token
