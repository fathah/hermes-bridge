# Knowledge

Accumulated facts about hermes-agent that the bridge depends on. Keep this up-to-date as hermes evolves — every entry here is a blast radius if it breaks.

## Hermes surface area (as of v0.10.0)

### Ports

- `:8642` — OpenAI-compatible chat API. Implemented in `gateway/platforms/api_server.py` using **aiohttp** (not FastAPI). Routes registered via `self._app.router.add_post(...)`. Static bearer auth using `API_SERVER_KEY` env var.
- `:9119` — FastAPI dashboard. Implemented in `hermes_cli/web_server.py` as a single `app = FastAPI(...)`. Ephemeral session token is injected into the root HTML:
  ```
  hermes_cli/web_server.py:2046 → <script>window.__HERMES_SESSION_TOKEN__="...";</script>
  ```
  Regenerated on every restart. No API to fetch it — we scrape the HTML.

### CLI commands that map to bridge gap-fills

- `hermes gateway start|stop|restart|status|install|uninstall|setup` — defined in `hermes_cli/gateway.py`. The bridge invokes `start/stop/restart` via `docker exec hermes hermes gateway <action>`.

### Dashboard routes we care about

From `hermes_cli/web_server.py` (grep `@app\.(get|post|put|delete)`):

- Config: `GET/PUT /api/config`, `GET /api/config/schema`, `GET /api/config/defaults`, `GET/PUT /api/config/raw`
- Env: `GET/PUT/DELETE /api/env`, `POST /api/env/reveal` (upstream rate-limited 5/30s)
- Sessions: `GET /api/sessions`, `GET /api/sessions/search`, `GET/DELETE /api/sessions/{id}`, `GET /api/sessions/{id}/messages`
- Status/model: `GET /api/status`, `GET /api/model/info`
- Cron (v1.1+): `GET/POST /api/cron/jobs`, `{PUT,DELETE} /api/cron/jobs/{id}`, `POST /api/cron/jobs/{id}/{pause,resume,trigger}`
- Skills (v1.1+): `GET /api/skills`, `PUT /api/skills/toggle`
- OAuth providers (v1.1+): `/api/providers/oauth/*`
- Logs/analytics (v1.1+): `GET /api/logs`, `GET /api/analytics/usage`
- Dashboard themes/plugins (out of scope): `/api/dashboard/*`

## Bridge contracts we must not break

- **No hermes imports.** Enforced by ruff `flake8-tidy-imports` banned-api rule in `pyproject.toml`. Bans `hermes`, `hermes_cli`, `gateway`, `agent`.
- **Only three upstream contracts:** HTTP, subprocess via `docker exec`, filesystem under `$HERMES_HOME` (`/opt/data`).
- **App factory, not module-level app.** Uvicorn runs `hermes_bridge.app:create_app --factory` so importing the module (e.g. in tests) doesn't require env vars.

## Local dev environment notes

- Local Python is 3.13 and 3.14; no 3.12 on this machine. `pyproject.toml` allows `>=3.12` and tests pass on 3.13. Production container pins 3.12 to match hermes.
- Testing uses `respx` to mock every upstream httpx call. `TestClient` (not raw `ASGITransport`) is used so the FastAPI lifespan runs and `app.state.chat_client` / `app.state.dashboard_token` get populated.
- Rate-limit defaults in tests are lowered via env: `BRIDGE_RATE_WRITE=5/10s`, `BRIDGE_RATE_READ=20/10s`.
