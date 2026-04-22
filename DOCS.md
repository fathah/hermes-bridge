# hermes-bridge API reference

Human-readable API docs. For the machine-readable spec used by mobile code-gen, see [`docs/openapi.yaml`](docs/openapi.yaml).

All routes are served from the bridge on port `8080`. Examples below assume:

```bash
export BRIDGE="http://localhost:8080"
export TOKEN="$BRIDGE_TOKEN"    # from your .env
```

---

## Conventions

### Authentication

Every route under `/api/*` requires a bearer token:

```
Authorization: Bearer <BRIDGE_TOKEN>
```

The token is the `BRIDGE_TOKEN` value from your `.env` (minimum 32 characters). `/health` is the only public route.

Comparison is timing-safe (`hmac.compare_digest`). A missing, malformed, or wrong token returns `401 {"detail":"unauthorized"}`.

### Rate limiting

Per-IP sliding-window limits, separately tracked for reads and writes:

| Bucket | Methods           | Default     | Env var              |
| ------ | ----------------- | ----------- | -------------------- |
| read   | `GET`             | `300/10s`   | `BRIDGE_RATE_READ`   |
| write  | `POST/PUT/DELETE/PATCH` | `30/10s` | `BRIDGE_RATE_WRITE`  |

When exceeded the bridge returns:

```
HTTP/1.1 429 Too Many Requests
Retry-After: <seconds>

{"detail":"rate limit exceeded"}
```

`POST /api/env/reveal` is additionally rate-limited by hermes upstream (5 req / 30s).

### Error format

Unless otherwise noted the bridge returns upstream responses verbatim (status code + body). Bridge-originated errors use:

```json
{"detail": "<message>"}
```

Common status codes:

| Status | Meaning |
|--------|---------|
| 400 | Invalid JSON body (bridge-side) |
| 401 | Missing / bad bearer token |
| 429 | Rate limit exceeded — inspect `Retry-After` |
| 502 | Upstream (hermes) returned 5xx or CLI subprocess failed |
| 503 | Hermes dashboard unreachable (token scrape failed) |

### Headers forwarded

- `X-Hermes-Session-Id` — forwarded both directions on `/api/chat/completions`. Used by hermes for opt-in session continuity.
- `X-Forwarded-For` — used to identify the client IP for rate limiting and the audit log.

### Audit log

Every mutation (`POST/PUT/DELETE/PATCH`) is appended as one JSON line to `$BRIDGE_AUDIT_LOG_PATH` (default `/opt/data/logs/bridge_audit.log`). Rotates at 10 MB. Each entry:

```json
{"ts":1714000000.12,"ip":"10.0.0.1","method":"PUT","path":"/api/config","status":200}
```

---

## Endpoints

### `GET /health` — liveness + upstream probes

**Auth:** public.
**Params:** none.

Returns 200 when the bridge and hermes `:8642/health` respond OK. The hermes `:9119/api/status` probe is reported in the response but is **not** required for a 200 — the dashboard can be down without failing liveness. Top-level `ok` still reflects all probes, so clients should read `checks.*` for a non-blocking view.

```bash
curl $BRIDGE/health
```

**200 OK**
```json
{
  "ok": true,
  "checks": {
    "bridge": {"ok": true},
    "hermes_chat": {"ok": true, "status": 200},
    "hermes_dashboard": {"ok": true, "status": 200}
  }
}
```

**503** — same shape, but `ok: false` somewhere. Field `error` is present when a probe raised.

---

### `POST /api/chat/completions` — OpenAI-compatible chat (proxy, streaming)

**Auth:** bearer.
**Upstream:** `POST :8642/v1/chat/completions` (hermes gateway API). Request body and response are OpenAI-format. See the hermes docs for the full chat schema.

Bridge behavior:

- Injects `Authorization: Bearer $HERMES_API_KEY` before forwarding.
- Auto-detects streaming: if request body has `"stream": true`, the response is an SSE stream (`text/event-stream`) piped chunk-by-chunk with no buffering. Otherwise the full JSON is returned.
- Forwards `X-Hermes-Session-Id` both directions.

**Request body (minimal):**
```json
{
  "model": "claude-opus-4-7",
  "messages": [
    {"role": "user", "content": "hello"}
  ],
  "stream": true
}
```

**Streaming example:**
```bash
curl -N $BRIDGE/api/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-opus-4-7","messages":[{"role":"user","content":"hi"}],"stream":true}'
```

Returns `data: {...}\n\n` frames terminating in `data: [DONE]\n\n`.

**Non-streaming example:** same command with `"stream": false`; returns a single JSON response (status and `content-type` passed through from upstream).

**Errors:**
- `400` — bridge could not parse your JSON body.
- Upstream errors (`401/400/5xx` from hermes) are forwarded unchanged.

---

### `GET /api/status` — hermes dashboard status (proxy)

**Auth:** bearer.
**Params:** none.
**Upstream:** `GET :9119/api/status`.

Returns hermes' status blob (model info, gateway state, uptime, etc.). Body shape follows upstream — don't hardcode schema in the client.

```bash
curl $BRIDGE/api/status -H "Authorization: Bearer $TOKEN"
```

---

### `GET /api/model/info` — active model info (proxy)

**Auth:** bearer.
**Params:** none.
**Upstream:** `GET :9119/api/model/info`.

---

### `GET /api/providers/llm` — API-key LLM provider catalog

**Auth:** bearer.
**Params:** none.
**Source:** bridge-composed from `GET :9119/api/env`.

Returns a curated list of API-key LLM providers (OpenRouter, Gemini, xAI, DeepSeek, Kimi, etc.), each enriched with connection status, the underlying env key entry (redacted value, `is_set`), any aliases, and the base-URL env entry. Intended for the mobile "Providers" screen — prefer this over parsing `/api/env` directly.

**200 OK**
```json
{
  "providers": [
    {
      "id": "openrouter",
      "name": "OpenRouter",
      "docs_url": "https://openrouter.ai/keys",
      "connected": true,
      "api_key": {"key": "OPENROUTER_API_KEY", "is_set": true, "redacted_value": "sk-or-…", "is_password": true, "description": "...", "url": null},
      "api_key_aliases": [],
      "base_url": {"key": "OPENROUTER_BASE_URL", "is_set": false, "redacted_value": null, "is_password": false, "description": "...", "url": null}
    }
  ]
}
```

**502** — upstream `/api/env` failed; `detail` and `status` included.

---

### `GET /api/providers/oauth` — OAuth provider catalog (proxy)

**Auth:** bearer.
**Params:** none.
**Upstream:** `GET :9119/api/providers/oauth`.

Read-only list of OAuth-capable providers and their connection state. OAuth start/submit/poll/revoke endpoints remain on the v1.1+ roadmap.

---

### `GET /api/tools/toolsets` — available toolsets (proxy)

**Auth:** bearer.
**Params:** none.
**Upstream:** `GET :9119/api/tools/toolsets`.

---

### `GET /api/skills` — skills catalog (proxy)

**Auth:** bearer.
**Params:** none.
**Upstream:** `GET :9119/api/skills`.

---

### `PUT /api/skills/toggle` — enable/disable a skill (proxy)

**Auth:** bearer (write bucket).
**Upstream:** `PUT :9119/api/skills/toggle`. Request body is forwarded verbatim; consult upstream for the exact shape.

---

### `GET /api/config` — full effective config (proxy)

**Auth:** bearer.
**Params:** none.
**Upstream:** `GET :9119/api/config`.

Returns the merged config hermes is currently using.

---

### `PUT /api/config` — patch config (proxy)

**Auth:** bearer (write bucket).
**Upstream:** `PUT :9119/api/config`. Upstream expects:

```json
{"config": { "<any keys>": "<any values>" }}
```

Only provided keys are merged; omitted keys are left unchanged. hermes may validate against its schema and return `400` on invalid values.

```bash
curl -X PUT $BRIDGE/api/config \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"config":{"model_name":"claude-opus-4-7"}}'
```

---

### `GET /api/config/schema` — config field metadata (cached)

**Auth:** bearer.
**Params:** none.
**Source:** cached at bridge startup from `GET :9119/api/config/schema`. If warm-up failed, falls through to a live upstream call on first request.

Returns the JSON-schema-ish metadata the mobile app uses to render config forms (types, descriptions, enums). Pair with `GET /api/config` to show current values next to field metadata.

---

### `GET /api/config/defaults` — default config values (proxy)

**Auth:** bearer.
**Params:** none.
**Upstream:** `GET :9119/api/config/defaults`.

---

### `GET /api/env` — list env vars (redacted)

**Auth:** bearer.
**Params:** none.
**Upstream:** `GET :9119/api/env`.

Returns the catalog of managed env vars with descriptions, categories, and **redacted** values. Use `POST /api/env/reveal` to unredact one.

---

### `PUT /api/env` — set an env var

**Auth:** bearer (write bucket).
**Upstream:** `PUT :9119/api/env`.

**Request body:**
```json
{"key": "ANTHROPIC_API_KEY", "value": "sk-ant-..."}
```

Both fields required.

---

### `DELETE /api/env` — unset an env var

**Auth:** bearer (write bucket).
**Upstream:** `DELETE :9119/api/env`.

**Request body:**
```json
{"key": "ANTHROPIC_API_KEY"}
```

The DELETE carries a JSON body; make sure your HTTP client sends `Content-Type: application/json`.

---

### `POST /api/env/reveal` — unredact a single env var

**Auth:** bearer (write bucket).
**Upstream:** `POST :9119/api/env/reveal`. Upstream rate-limited `5 req / 30s`.

**Request body:**
```json
{"key": "ANTHROPIC_API_KEY"}
```

> Mobile clients should gate this endpoint behind biometric confirmation (Face ID / fingerprint) before sending.

---

### `GET /api/sessions` — list sessions

**Auth:** bearer.
**Query params:**

| Name    | Type | Default | Notes                              |
|---------|------|---------|------------------------------------|
| `limit` | int  | `20`    | Page size.                         |
| `offset`| int  | `0`     | Offset for pagination.             |

**Upstream:** `GET :9119/api/sessions`.

```bash
curl "$BRIDGE/api/sessions?limit=50&offset=0" -H "Authorization: Bearer $TOKEN"
```

---

### `GET /api/sessions/search` — fulltext search

**Auth:** bearer.
**Query params:**

| Name    | Type | Default | Notes                              |
|---------|------|---------|------------------------------------|
| `q`     | str  | `""`    | Search query.                      |
| `limit` | int  | `20`    | Page size.                         |

**Upstream:** `GET :9119/api/sessions/search`.

```bash
curl "$BRIDGE/api/sessions/search?q=deploy&limit=10" -H "Authorization: Bearer $TOKEN"
```

---

### `GET /api/sessions/{session_id}` — session metadata

**Auth:** bearer.
**Path params:** `session_id` (str).
**Upstream:** `GET :9119/api/sessions/{id}`.

---

### `GET /api/sessions/{session_id}/messages` — session transcript

**Auth:** bearer.
**Path params:** `session_id` (str).
**Query params:** forwarded untouched to upstream (hermes may support pagination here — consult the hermes version you're pinned to).
**Upstream:** `GET :9119/api/sessions/{id}/messages`.

---

### `DELETE /api/sessions/{session_id}` — delete a session

**Auth:** bearer (write bucket).
**Path params:** `session_id` (str).
**Upstream:** `DELETE :9119/api/sessions/{id}`.

---

### `GET /api/cron/jobs` — list cron jobs (proxy)

**Auth:** bearer.
**Query params:** forwarded untouched.
**Upstream:** `GET :9119/api/cron/jobs`.

---

### `POST /api/cron/jobs` — create a cron job (proxy)

**Auth:** bearer (write bucket).
**Upstream:** `POST :9119/api/cron/jobs`. Request body forwarded verbatim.

---

### `PUT /api/cron/jobs/{job_id}` — update a cron job (proxy)

**Auth:** bearer (write bucket).
**Path params:** `job_id` (str).
**Upstream:** `PUT :9119/api/cron/jobs/{job_id}`.

---

### `DELETE /api/cron/jobs/{job_id}` — delete a cron job (proxy)

**Auth:** bearer (write bucket).
**Path params:** `job_id` (str).
**Upstream:** `DELETE :9119/api/cron/jobs/{job_id}`.

---

### `POST /api/cron/jobs/{job_id}/{pause,resume,trigger}` — cron job actions (proxy)

**Auth:** bearer (write bucket).
**Path params:** `job_id` (str); action is one of `pause`, `resume`, `trigger`.
**Upstream:** `POST :9119/api/cron/jobs/{job_id}/{action}`. No request body.

```bash
curl -X POST "$BRIDGE/api/cron/jobs/$JOB/trigger" -H "Authorization: Bearer $TOKEN"
```

---

### `GET /api/logs` — recent hermes logs (proxy)

**Auth:** bearer.
**Query params:** forwarded untouched (hermes supports `lines`, and may support `since`/`level` — consult the pinned hermes version).
**Upstream:** `GET :9119/api/logs`.

```bash
curl "$BRIDGE/api/logs?lines=300" -H "Authorization: Bearer $TOKEN"
```

---

### `GET /api/analytics/usage` — usage analytics (proxy)

**Auth:** bearer.
**Query params:** forwarded untouched (e.g. `days`).
**Upstream:** `GET :9119/api/analytics/usage`.

```bash
curl "$BRIDGE/api/analytics/usage?days=30" -H "Authorization: Bearer $TOKEN"
```

---

### `POST /api/gateway/start` — start the messaging gateway

**Auth:** bearer (write bucket).
**Params:** none.
**Implementation:** runs `docker exec $HERMES_CONTAINER_NAME hermes gateway start` (30 s timeout).

**200 OK**
```json
{"action":"start","ok":true,"stdout":"...","stderr":""}
```

**502 Bad Gateway** — non-zero exit code. `detail` contains `action`, `returncode`, `stdout`, `stderr`.

---

### `POST /api/gateway/stop` — stop the messaging gateway

Same shape as `start`; action is `"stop"`.

---

### `POST /api/gateway/restart` — restart the messaging gateway

Same shape as `start`; action is `"restart"`. Use this after changing gateway-related env vars or platform credentials.

---

## Not implemented in v1

The following mobile-facing endpoints are on the v1.1+ roadmap (see [PLAN.md §11](PLAN.md)). Calling them today returns `404`.

**Proxies (already exist upstream, just need wiring):**

- `POST /api/providers/oauth/{id}/{start,submit}`, `GET /api/providers/oauth/{id}/poll/{session_id}`, `DELETE /api/providers/oauth/{id}`, `DELETE /api/providers/oauth/sessions/{session_id}`
- `GET/PUT /api/config/raw`

**Gap-fills (bridge-implemented, no upstream HTTP yet):**

- `GET/PUT/DELETE /api/personalities/{name}` — SOUL.md-style persona files
- `GET/POST/DELETE /api/mcp/servers[/{name}]`
- `GET/PUT /api/memories/{file}` — `MEMORY.md`, `USER.md`, `SOUL.md`
- `GET /api/pairing/pending`, `POST /api/pairing/{approve,revoke}`
- `POST /api/skills`, `DELETE /api/skills/{name}`
- `POST /api/backup`, `POST /api/restore`
- `POST /api/auth/rotate` — rotate `BRIDGE_TOKEN` without restart
- `POST /api/push/register` — register FCM device token

---

## Versioning

The bridge's major.minor tracks compatibility with a specific hermes minor version:

| hermes-bridge | hermes-agent | Flutter app |
| ------------- | ------------ | ----------- |
| 0.1.x         | 0.10.x       | 0.1.x       |

Breaking changes to bridge endpoints will bump the bridge minor version. Adding new optional fields to response bodies is non-breaking. Because most bodies are forwarded verbatim from hermes, upstream-shape changes will show through — the bridge doesn't normalize them.
