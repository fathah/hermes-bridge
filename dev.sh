#!/usr/bin/env bash
# Run hermes-bridge locally (with uvicorn --reload) while keeping
# hermes-agent in Docker. For fast dev iteration without rebuilds.
#
# Usage:   ./dev.sh
# Stop:    Ctrl-C (bridge); `docker compose -f docker-compose.yml -f docker-compose.dev.yml down` (hermes)

set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE=".env"
DEV_OVERRIDE="docker-compose.dev.yml"
DEV_DATA_DIR=".dev-data"
VENV_DIR=".venv"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: $ENV_FILE not found. Run ./start.sh once to generate tokens." >&2
    exit 1
fi

# Generate the dev compose override (exposes hermes :8642 on localhost).
if [ ! -f "$DEV_OVERRIDE" ]; then
    cat > "$DEV_OVERRIDE" <<'YAML'
# Dev-only override: expose hermes ports on localhost so a local bridge
# process can reach them. Do NOT use in production.
services:
  hermes:
    ports:
      - "127.0.0.1:8642:8642"
  hermes-dashboard:
    ports:
      - "127.0.0.1:9119:9119"
YAML
    echo "Created $DEV_OVERRIDE"
fi

if ! docker info >/dev/null 2>&1; then
    echo "Error: docker daemon is not running." >&2
    exit 1
fi

echo "Starting hermes + dashboard in Docker (with exposed ports)..."
docker compose --profile dashboard -f docker-compose.yml -f "$DEV_OVERRIDE" up -d hermes hermes-dashboard

mkdir -p "$DEV_DATA_DIR/logs"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating venv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
    "$VENV_DIR/bin/pip" install -e ".[dev]"
fi

# Load .env (BRIDGE_TOKEN, HERMES_API_KEY, HERMES_CONTAINER_NAME).
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Local overrides: point at the Docker-exposed ports; keep data on the host.
export HERMES_CHAT_URL="http://localhost:8642"
export HERMES_DASH_URL="http://localhost:9119"
export HERMES_HOME="$(pwd)/$DEV_DATA_DIR"
export BRIDGE_AUDIT_LOG_PATH="$(pwd)/$DEV_DATA_DIR/logs/bridge_audit.log"
export BRIDGE_HOST="${BRIDGE_HOST:-0.0.0.0}"
export BRIDGE_PORT="${BRIDGE_PORT:-8080}"
export BRIDGE_LOG_LEVEL="${BRIDGE_LOG_LEVEL:-DEBUG}"

echo
echo "Bridge → http://localhost:${BRIDGE_PORT} (auto-reloads on file save)"
echo "Health: curl -H 'Authorization: Bearer \$BRIDGE_TOKEN' http://localhost:${BRIDGE_PORT}/health"
echo

exec "$VENV_DIR/bin/uvicorn" hermes_bridge.app:create_app \
    --factory \
    --reload \
    --reload-dir src \
    --host "$BRIDGE_HOST" \
    --port "$BRIDGE_PORT"


# Ctrl-C stops the bridge. hermes keeps running in Docker — use docker compose -f docker-compose.yml -f docker-compose.dev.yml down when you're done.
# Gateway lifecycle (docker exec hermes ...) works because your host has docker.
# .dev-data/ and .venv/ should be in .gitignore if they aren't already.
# When you're done with dev, ./start.sh still runs the full Docker setup unchanged.