#!/usr/bin/env bash
# Start hermes-bridge (and the bundled hermes) via docker compose.
# On first run, generates BRIDGE_TOKEN and HERMES_API_KEY into .env.
# Re-runs are idempotent: existing .env values are preserved.

set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE=".env"

gen_token() {
    python3 -c "import secrets; print(secrets.token_urlsafe(32))"
}

ensure_var() {
    local key="$1"
    if ! grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
        echo "${key}=$(gen_token)" >> "$ENV_FILE"
        echo "  generated ${key}"
    fi
}

if [ ! -f "$ENV_FILE" ]; then
    touch "$ENV_FILE"
    echo "Creating $ENV_FILE"
fi

ensure_var BRIDGE_TOKEN
ensure_var HERMES_API_KEY

if ! docker info >/dev/null 2>&1; then
    echo "Error: docker daemon is not running." >&2
    exit 1
fi

docker compose up -d --build

echo
echo "Bridge is up on http://localhost:8080"
echo "Health check:"
BRIDGE_TOKEN="$(grep -E '^BRIDGE_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
echo "  curl -H 'Authorization: Bearer $BRIDGE_TOKEN' http://localhost:8080/health"
echo
echo "Logs:    docker compose logs -f bridge"
echo "Stop:    docker compose down"
