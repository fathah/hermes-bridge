# Build Spec — `hermes-bridge`

**Audience:** An AI (or engineer) who will scaffold and implement a new project called `hermes-bridge` from scratch. You have zero prior context. Everything you need to start is in this document.

**What you are building:** A FastAPI companion service for [hermes-agent](https://github.com/NousResearch/hermes-agent) that sits in front of hermes and exposes a **stable, mobile-ready HTTP API** for a Flutter app. The bridge proxies hermes' existing endpoints, fills gaps hermes doesn't have HTTP for, and owns auth/security concerns that don't belong upstream.

**What you are NOT building:** A fork of hermes. A replacement for hermes. A Go service. A web UI. The Flutter mobile app itself (that's a separate project).

---

## 1. Why this exists — read this before writing a line

Hermes Agent is an open-source AI agent that runs on a VPS via Docker. It already ships two HTTP servers:

- **`:8642`** — OpenAI-compatible chat API (`/v1/chat/completions` streaming, `/v1/responses`, SSE events). Auth: static Bearer token from `API_SERVER_KEY` env var.
- **`:9119`** — FastAPI dashboard (config, env vars, sessions, cron, skills, analytics, OAuth). Auth: **ephemeral** Bearer token regenerated on every restart and injected into the SPA HTML. This ephemeral-token design is the main problem for mobile clients.

Additionally, hermes has significant gaps — features that are CLI-only with no HTTP surface:

- Gateway lifecycle (start/stop/restart messaging gateway)
- Personalities (SOUL.md-style persona files)
- MCP server management
- Memories (`MEMORY.md`, `USER.md`)
- Pairing approval for messaging platforms
- Skill CRUD (only enable/disable exists over HTTP)

A mobile user who wants to fully manage their VPS-hosted hermes from their phone needs all of this plus a stable auth model. **The bridge fills these gaps without modifying hermes.**

### The hard architectural rule

The bridge talks to hermes over exactly three contracts:

1. **HTTP** — the two ports above.
2. **CLI subprocess** — `subprocess.run(["hermes", ...])` for things with no HTTP equivalent.
3. **Filesystem** — reads/writes to `/opt/data/` (hermes' `HERMES_HOME`) for config YAML, `.env`, session SQLite, skills dir, personalities, `MEMORY.md`, etc.

**The bridge never imports any hermes Python module.** No `from hermes.*`, no `from hermes_cli.*`, no `from gateway.*`, no `from agent.*`. Enforce this with a lint rule in CI. This is what makes the bridge survive hermes upgrades.

---

## 2. Deployment shape — the thing the user sees

One `docker compose up -d` starts everything. One port exposed. One token.

```
┌─────────────────────────────────────────────────────┐
│  Docker host / VPS                                  │
│                                                     │
│   ┌──────────────┐        ┌──────────────────┐      │
│   │  hermes      │◀──────▶│  hermes-bridge    │     │
│   │  (Python)    │  HTTP  │  (FastAPI :8080) │─────▶│ public
│   │  :8642 chat  │        │                  │      │
│   │  :9119 dash  │        │  subprocess      │      │
│   │              │        │  + filesystem    │      │
│   └──────┬───────┘        └──────────┬───────┘      │
│          │                           │              │
│          └──── /opt/data volume ─────┘              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

Only `:8080` (the bridge) is published. `:8642` and `:9119` live on the internal Docker network.

### `docker-compose.yml` (authoritative)

```yaml
services:
  hermes:
    image: ghcr.io/nousresearch/hermes-agent:v0.10.0 # pin exact version
    volumes:
      - hermes-data:/opt/data
    environment:
      API_SERVER_ENABLED: "true"
      API_SERVER_KEY: ${HERMES_API_KEY} # shared with bridge via env
      API_SERVER_HOST: 0.0.0.0
      API_SERVER_PORT: "8642"
      HERMES_DASHBOARD_HOST: 0.0.0.0
      HERMES_DASHBOARD_PORT: "9119"
    networks:
      - internal
    # NOTE: no ports published — only the bridge is reachable

  bridge:
    build: . # or use published image
    depends_on:
      - hermes
    ports:
      - "8080:8080"
    volumes:
      - hermes-data:/opt/data # same volume, read+write
    environment:
      BRIDGE_TOKEN: ${BRIDGE_TOKEN} # user-provided stable token
      HERMES_CHAT_URL: http://hermes:8642
      HERMES_DASH_URL: http://hermes:9119
      HERMES_API_KEY: ${HERMES_API_KEY}
      HERMES_HOME: /opt/data
    networks:
      - internal

volumes:
  hermes-data:

networks:
  internal:
```

The user fills `.env` with `BRIDGE_TOKEN` (random 32 bytes) and `HERMES_API_KEY` (random 32 bytes). `docker compose up -d`. Done.

---

## 3. Project location and naming

- **On disk:** `/Users/fathah/Desktop/opensource/hermes-bridge/` — sibling to `/Users/fathah/Desktop/opensource/hermes-agent/`. They are independent git repos.
- **Package name:** `hermes-bridge` (PyPI-safe).
- **Python import name:** `hermes_bridge`.
- **Public API port:** `8080`.
- **License:** MIT.

---

## 4. v1 scope — ship this, nothing more

Six deliverables. If you are tempted to add a seventh, stop.

1. **Stable auth.** User-provided `BRIDGE_TOKEN`. Bearer on every `/api/*` request. `hmac.compare_digest`. Per-IP rate limiting (sliding window, e.g. 30 req / 10s for writes, more for reads). Return 429 with `Retry-After`.
2. **Chat proxy.** `POST /api/chat/completions` — stream passthrough of `POST :8642/v1/chat/completions`. Auto-detect `stream: true` and SSE-pipe. Inject `Authorization: Bearer $HERMES_API_KEY` upstream; accept `Authorization: Bearer $BRIDGE_TOKEN` from client.
3. **Config proxy.** `GET/PUT /api/config`, `GET /api/config/schema`, `GET/PUT /api/env`, `POST /api/env/reveal`. Auth to upstream `:9119` using the ephemeral dashboard token (see §7 on how to get it).
4. **Sessions proxy.** `GET /api/sessions`, `GET /api/sessions/{id}`, `GET /api/sessions/{id}/messages`, `GET /api/sessions/search`, `DELETE /api/sessions/{id}`.
5. **Gateway lifecycle — the one gap-fill in v1 to prove the pattern.** `POST /api/gateway/restart`, `POST /api/gateway/stop`, `POST /api/gateway/start`. Implement via `subprocess.run(["hermes", "gateway", "restart"])` inside the hermes container. (Use `docker exec` if the bridge container can't reach hermes' CLI — decide at build time; see §8.)
6. **Health.** `GET /health` — aggregates: bridge alive, hermes `:8642/health`, hermes `:9119/api/status`. Returns 200 only if all three are OK.

Everything else (cron, skills, toolsets, OAuth, analytics, logs proxy, personalities, MCP, memories, pairing, push notifications, backup/restore, token rotation endpoint) is **v1.1+**. Leave stubs if you want, but don't implement.

---

## 5. File layout to scaffold

```
hermes-bridge/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── src/
│   └── hermes_bridge/
│       ├── __init__.py
│       ├── app.py                   # FastAPI() + lifespan + middleware + route mounts
│       ├── config.py                # Settings via pydantic-settings (env vars)
│       ├── auth.py                  # BRIDGE_TOKEN check + rate limiter + audit log
│       ├── upstream.py              # httpx clients for :8642 and :9119
│       ├── dashboard_token.py       # scrape ephemeral token from hermes SPA HTML
│       ├── cli.py                   # subprocess wrappers for `hermes ...` commands
│       ├── fs.py                    # filesystem helpers for /opt/data
│       └── routes/
│           ├── __init__.py
│           ├── health.py
│           ├── chat.py              # SSE streaming proxy
│           ├── config.py            # GET/PUT /api/config + env
│           ├── sessions.py          # sessions list/get/search/delete
│           └── gateway.py           # lifecycle (the gap-fill)
├── tests/
│   ├── conftest.py                  # fixtures: mock upstream, fastapi TestClient
│   ├── test_auth.py
│   ├── test_health.py
│   ├── test_chat_stream.py
│   ├── test_config_proxy.py
│   └── test_gateway_lifecycle.py
└── docs/
    └── openapi.yaml                 # generated from FastAPI; committed for mobile app
```

---

## 6. Tech stack — do not deviate without reason

- **Python 3.12** (match what hermes targets).
- **FastAPI** + **uvicorn[standard]** — web framework + server.
- **httpx** (async) — upstream HTTP client. Use one shared `AsyncClient` per upstream base URL, stored on `app.state`. Reuse connections.
- **sse-starlette** (optional but recommended) — for clean SSE responses. Pure FastAPI `StreamingResponse` also works.
- **pydantic v2** + **pydantic-settings** — models and env-var config.
- **pytest** + **pytest-asyncio** + **httpx** (test client) — tests.
- **ruff** — linting, including a custom rule banning `from hermes*` imports.
- **mypy** — strict.

No Celery, no Redis, no database in v1. The bridge is stateless except for the audit log (which is a rotating file).

---

## 7. Solving the ephemeral-dashboard-token problem

Hermes' `:9119` regenerates its auth token on every restart and injects it into the SPA HTML at `GET /` as `window.__HERMES_SESSION_TOKEN__="..."`. There is no API to fetch it. The bridge MUST acquire it without modifying hermes.

**Pattern** (in `dashboard_token.py`):

1. On bridge startup: `httpx.get(f"{HERMES_DASH_URL}/")` and regex out the token from the HTML:
   ```python
   import re
   HTML_TOKEN_RE = re.compile(r'window\.__HERMES_SESSION_TOKEN__\s*=\s*"([^"]+)"')
   ```
2. Cache the token in `app.state.dashboard_token`.
3. Every upstream request to `:9119` attaches `Authorization: Bearer <cached_token>`.
4. If upstream returns 401, re-scrape the HTML (hermes restarted) and retry exactly once.
5. On fatal scrape failure, log and return 503 from bridge routes that need it.

Also fetch and cache at startup:

- `GET :9119/api/config/schema` → for field metadata when mobile renders the settings UI
- `GET :9119/api/env` → for env-var catalog (descriptions, categories, redaction)

These are the "don't hardcode schema" escape hatches. When hermes adds new env vars, they appear automatically.

**Upstream PR backlog** (for later, not v1): persuade hermes upstream to accept a `HERMES_DASHBOARD_TOKEN` env var for stable tokens. When that lands, the scrape becomes the fallback path.

---

## 8. SSE streaming — the one tricky part of v1

`POST /api/chat/completions` must stream. The naive "read full upstream response, return it" approach will break chat. Do this:

```python
# routes/chat.py (sketch — fill in details, imports, error handling)
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

@router.post("/api/chat/completions")
async def chat_completions(req: Request):
    body = await req.json()
    client = req.app.state.chat_client            # httpx.AsyncClient, base_url = :8642
    headers = {"Authorization": f"Bearer {settings.HERMES_API_KEY}"}
    if body.get("stream"):
        async def stream():
            async with client.stream("POST", "/v1/chat/completions",
                                     json=body, headers=headers) as upstream:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})
    # non-streaming
    resp = await client.post("/v1/chat/completions", json=body, headers=headers)
    return Response(content=resp.content, status_code=resp.status_code,
                    media_type=resp.headers.get("content-type"))
```

**Critical details:**

- Use `client.stream(...)` as an async context manager so the upstream connection is cleaned up even if the client disconnects mid-stream.
- If the client disconnects, `aiter_bytes()` will raise; catch and close cleanly. FastAPI handles this but verify with a test.
- Do not buffer. Yield chunks as they arrive.
- Forward the `X-Hermes-Session-Id` header both directions if present.

**Reference code worth reading before you write yours:** [`jettoptx/joe-optx-hermes-api/src/hermes_optx_api/routes/chat.py`](https://github.com/jettoptx/joe-optx-hermes-api/blob/master/src/hermes_optx_api/routes/chat.py) — they solved SSE streaming against hermes. Read it, don't depend on it. Their repo is single-maintainer, 18 days old, coupled to the OPTX ecosystem (Solana billing, SpacetimeDB, JettChat) — not suitable as a dependency.

---

## 9. Auth design

### Settings (`config.py`)

Env vars the bridge reads:

| Var                     | Required | Default                           | Purpose                                                               |
| ----------------------- | -------- | --------------------------------- | --------------------------------------------------------------------- |
| `BRIDGE_TOKEN`          | yes      | —                                 | Bearer token mobile app sends. ≥ 32 chars. Reject startup if shorter. |
| `HERMES_CHAT_URL`       | yes      | `http://hermes:8642`              | Upstream chat API                                                     |
| `HERMES_DASH_URL`       | yes      | `http://hermes:9119`              | Upstream dashboard                                                    |
| `HERMES_API_KEY`        | yes      | —                                 | Shared with hermes via compose `.env`; used to call `:8642`           |
| `HERMES_HOME`           | yes      | `/opt/data`                       | Mounted volume root                                                   |
| `BRIDGE_HOST`           | no       | `0.0.0.0`                         | uvicorn bind                                                          |
| `BRIDGE_PORT`           | no       | `8080`                            | uvicorn port                                                          |
| `BRIDGE_LOG_LEVEL`      | no       | `INFO`                            |                                                                       |
| `BRIDGE_AUDIT_LOG_PATH` | no       | `/opt/data/logs/bridge_audit.log` |                                                                       |
| `BRIDGE_RATE_WRITE`     | no       | `30/10s`                          | writes per window                                                     |
| `BRIDGE_RATE_READ`      | no       | `300/10s`                         | reads per window                                                      |

### Middleware (`auth.py`)

1. Extract `Authorization: Bearer <token>` header.
2. `hmac.compare_digest(token, settings.BRIDGE_TOKEN)` → 401 on mismatch.
3. Per-IP sliding-window rate limit — different limits for GET vs mutation methods. 429 with `Retry-After` on exceed.
4. Exempt `/health` from auth. Nothing else.
5. On mutation (`POST`/`PUT`/`DELETE`/`PATCH`), append to audit log: timestamp, IP, method, path, response status. JSON-lines. Rotate at 10 MB.

No token rotation endpoint in v1. Rotation in v1 = change env var, `docker compose up -d`. Add `POST /api/auth/rotate` in v1.1.

---

## 10. The hermes API surface — what you are wrapping

This is the catalogue of upstream routes the bridge proxies or wraps. Not exhaustive for v1 — only the ones in §4 scope need to work in v1.

### Upstream `:8642` (chat — from `gateway/platforms/api_server.py`)

```
GET    /health
GET    /health/detailed
GET    /v1/models
POST   /v1/chat/completions         ← v1 proxy this (streaming)
POST   /v1/responses
GET    /v1/responses/{response_id}
DELETE /v1/responses/{response_id}
POST   /v1/runs
GET    /v1/runs/{run_id}/events
# jobs endpoints exist but use dashboard cron endpoints instead
```

Auth: `Bearer $HERMES_API_KEY`.

### Upstream `:9119` (dashboard — from `hermes_cli/web_server.py`)

```
# --- v1 proxy these ---
GET    /api/status
GET    /api/model/info
GET    /api/config
PUT    /api/config
GET    /api/config/schema
GET    /api/config/defaults
GET    /api/env
PUT    /api/env
DELETE /api/env
POST   /api/env/reveal              ← rate-limited upstream (5/30s)
GET    /api/sessions
GET    /api/sessions/{id}
GET    /api/sessions/{id}/messages
DELETE /api/sessions/{id}
GET    /api/sessions/search

# --- v1.1+: proxy later ---
GET    /api/config/raw
PUT    /api/config/raw
GET    /api/cron/jobs
POST   /api/cron/jobs
PUT    /api/cron/jobs/{id}
POST   /api/cron/jobs/{id}/pause
POST   /api/cron/jobs/{id}/resume
POST   /api/cron/jobs/{id}/trigger
DELETE /api/cron/jobs/{id}
GET    /api/skills
PUT    /api/skills/toggle
GET    /api/tools/toolsets
GET    /api/providers/oauth
POST   /api/providers/oauth/{provider_id}/start
POST   /api/providers/oauth/{provider_id}/submit
GET    /api/providers/oauth/{provider_id}/poll/{session_id}
DELETE /api/providers/oauth/{provider_id}
DELETE /api/providers/oauth/sessions/{session_id}
GET    /api/logs
GET    /api/analytics/usage
```

Auth: scraped ephemeral token (see §7).

---

## 11. Bridge's public API — what mobile sees

All routes under `/api/*` require `Authorization: Bearer $BRIDGE_TOKEN`. `/health` is public.

### v1 endpoints (must work)

```
GET    /health
POST   /api/chat/completions             # proxy + SSE
GET    /api/status                       # proxy
GET    /api/model/info                   # proxy
GET    /api/config                       # proxy
PUT    /api/config                       # proxy
GET    /api/config/schema                # cached at startup, served from memory
GET    /api/env                          # proxy, with schema merged in
PUT    /api/env                          # proxy
DELETE /api/env                          # proxy
POST   /api/env/reveal                   # proxy + extra local rate limit (biometric gate on client)
GET    /api/sessions                     # proxy
GET    /api/sessions/{id}                # proxy
GET    /api/sessions/{id}/messages       # proxy
GET    /api/sessions/search              # proxy
DELETE /api/sessions/{id}                # proxy
POST   /api/gateway/restart              # subprocess gap-fill
POST   /api/gateway/stop                 # subprocess gap-fill
POST   /api/gateway/start                # subprocess gap-fill
```

### v1.1+ endpoints (do not implement yet; leave routes file stubs)

```
# Proxies for existing upstream routes
GET    /api/cron/jobs
POST   /api/cron/jobs
...

# Gap-fills (bridge implements directly)
GET    /api/personalities
PUT    /api/personalities/{name}
DELETE /api/personalities/{name}

GET    /api/mcp/servers
POST   /api/mcp/servers
DELETE /api/mcp/servers/{name}

GET    /api/memories
PUT    /api/memories/{file}              # MEMORY.md, USER.md, SOUL.md

GET    /api/pairing/pending
POST   /api/pairing/approve
POST   /api/pairing/revoke

POST   /api/skills                       # create
DELETE /api/skills/{name}

POST   /api/backup                       # tar /opt/data
POST   /api/restore                      # untar

POST   /api/auth/rotate                  # change BRIDGE_TOKEN without restart

POST   /api/push/register                # device token for FCM
```

Ignore v1.1+ in v1. Listed here so you understand the trajectory and don't paint yourself into a corner.

---

## 12. Rules the CI must enforce

1. **No hermes imports.** Ruff rule:
   ```toml
   [tool.ruff.lint.flake8-tidy-imports.banned-api]
   "hermes" = { msg = "Do not import from hermes internals; use HTTP/CLI/filesystem." }
   "hermes_cli" = { msg = "Do not import from hermes internals." }
   "gateway" = { msg = "Do not import from hermes internals." }
   "agent" = { msg = "Do not import from hermes internals." }
   ```
2. **Type-check.** `mypy --strict src/`.
3. **Test.** `pytest` must pass. Coverage target: 70% for v1, raise to 85% by v2.
4. **Format.** `ruff format --check`.

---

## 13. Testing expectations

### Unit tests

- **`test_auth.py`** — valid token → 200; invalid → 401; missing → 401; rate limit hits → 429 with `Retry-After`.
- **`test_health.py`** — upstream up → 200; one upstream down → 503 with diagnosis.
- **`test_chat_stream.py`** — mock upstream `httpx` returning SSE chunks; verify chunks arrive in order without buffering.
- **`test_config_proxy.py`** — verify auth injection, header forwarding, error pass-through.
- **`test_gateway_lifecycle.py`** — mock `subprocess.run`; verify exit code propagation.

### Integration test

One end-to-end with real hermes in Docker: `docker compose up -d`, wait for health, run a chat request, assert streaming works. Gate behind `make integration` so CI can run it but local devs aren't forced to.

---

## 14. Dockerfile sketch

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY src ./src
EXPOSE 8080
CMD ["uvicorn", "hermes_bridge.app:app", "--host", "0.0.0.0", "--port", "8080"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1
```

For CLI subprocess calls to hermes, the bridge container does NOT have `hermes` installed. Options:

- **Option A (recommended):** Bridge invokes hermes CLI via `docker exec hermes hermes ...`. Requires mounting the docker socket into the bridge container (`-v /var/run/docker.sock:/var/run/docker.sock`). Security note: socket access = root on host. Document the trade-off.
- **Option B:** Bridge sends a signal/HTTP request to a small helper endpoint the hermes container exposes. Requires upstream change — not in v1.
- **Option C:** For v1's single gap-fill (gateway restart), shell into the hermes container from compose via `exec`. Use option A; document it.

---

## 15. README content

The project README should include, in this order:

1. What it is (2-sentence pitch, prominently links to [hermes-agent](https://github.com/NousResearch/hermes-agent)).
2. Quickstart: `git clone`, `cp .env.example .env`, edit tokens, `docker compose up -d`.
3. Compatibility matrix:
   | hermes-bridge | hermes-agent | Flutter app |
   |---|---|---|
   | 0.1.x | 0.10.x | 0.1.x |
4. Architecture diagram (reuse the ASCII one from §2).
5. API reference — point to `docs/openapi.yaml`.
6. Security notes: stable token, biometric gate recommended for `/env/reveal`, TLS via reverse proxy.
7. FAQ: "why not upstream?", "why not Tailscale?", "what happens when hermes upgrades?" (answer: version pin + CI tests against new versions).
8. Link to `jettoptx/joe-optx-hermes-api` as prior art / alternative.

---

## 16. What you MUST NOT do

- Do not fork hermes.
- Do not modify hermes source code.
- Do not import from `hermes`, `hermes_cli`, `gateway`, `agent`, or any other hermes module.
- Do not ship a web UI. That's the Flutter app's job.
- Do not implement push notifications, backup, or v1.1+ endpoints in v1.
- Do not add a database. The bridge is stateless.
- Do not re-invent route logic that upstream already has — proxy it.
- Do not hardcode env-var catalogs or config schemas — fetch at startup (§7).
- Do not use Go, Rust, or TypeScript. The decision is FastAPI. Settled.

---

## 17. What you SHOULD do

- Read [hermes-agent/gateway/platforms/api_server.py](https://github.com/NousResearch/hermes-agent/blob/main/gateway/platforms/api_server.py) and [hermes-agent/hermes_cli/web_server.py](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/web_server.py) before you write any proxy code.
- Read [jettoptx/joe-optx-hermes-api](https://github.com/jettoptx/joe-optx-hermes-api) `src/hermes_optx_api/routes/chat.py` and `app.py` for SSE proxy and capability-probing patterns.
- Commit the generated `docs/openapi.yaml` so the Flutter app can code-gen DTOs against a stable spec.
- Write the README and CI before the second feature. First feature must ship with tests.
- Favor small PRs with passing tests over big sweeping commits.

---

## 18. Definition of done for v1

Check every box:

- [ ] `hermes-bridge/` repo exists, git-initialized.
- [ ] `docker compose up -d` starts hermes + bridge. Only port 8080 published.
- [ ] `curl -H "Authorization: Bearer $BRIDGE_TOKEN" http://localhost:8080/health` returns 200 when hermes is up.
- [ ] Requests without the token return 401.
- [ ] Excessive requests return 429 with `Retry-After`.
- [ ] `POST /api/chat/completions` with `stream: true` streams tokens via SSE.
- [ ] `GET /api/config` and `PUT /api/config` round-trip correctly.
- [ ] `GET /api/env` shows redacted values; `POST /api/env/reveal` shows unredacted (rate-limited).
- [ ] `GET /api/sessions` returns paginated session list.
- [ ] `POST /api/gateway/restart` restarts the gateway inside the hermes container.
- [ ] All tests pass (`pytest`), lints pass (`ruff check`, `mypy --strict`), format clean.
- [ ] No hermes imports anywhere (CI-enforced).
- [ ] README is complete per §15.
- [ ] `docs/openapi.yaml` committed.
- [ ] Works end-to-end when pointed at `ghcr.io/nousresearch/hermes-agent:v0.10.0`.

Once every box is checked, tag `v0.1.0` and stop. Plan v1.1 in a separate doc.

---

## 19. Tiny glossary

- **hermes / hermes-agent** — the upstream AI agent project. Python. MIT.
- **bridge / hermes-bridge** — the FastAPI layer you are building.
- **Flutter app** — the mobile client that talks to the bridge over HTTP. Built elsewhere, not your concern.
- **Gap-fill** — a bridge endpoint that implements functionality hermes doesn't expose over HTTP (uses CLI or filesystem).
- **Proxy** — a bridge endpoint that forwards to an existing hermes HTTP endpoint with auth rewritten.
- **Upstream** — hermes. Always refers to the agent, not the git sense.
- **Ephemeral token** — hermes' dashboard token, regenerated on every restart. See §7.

---

_End of spec. Start by reading §1–§4, then scaffold §5, then implement §4's six deliverables in order. Ship v1. Stop._
