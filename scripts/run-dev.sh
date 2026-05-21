#!/usr/bin/env bash
# run-dev.sh — bring up the full chat-server dev stack and stream both servers' logs.
#
# Steps:
#   1. Bring up `database` and `minio` containers (if not already healthy).
#   2. Apply alembic migrations to the dev DB (idempotent).
#   3. Ensure the MinIO `chat-files` bucket exists (the lifespan hook swallows errors).
#   4. Start the Python FastAPI app on :8000 with the host-side MinIO endpoint override.
#   5. Start the Go chatgw on :8080 pointed at the Python app.
#   6. Tail both servers' logs in the foreground. Ctrl-C tears everything down.
#
# Run from the InsurancePlatformPy/ project root, or from anywhere — paths resolve via realpath.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GO_DIR="$(cd "$PY_DIR/../InsurancePlatform" && pwd)"

PYTHON_LOG="${PYTHON_LOG:-/tmp/chatserver-python.log}"
CHATGW_LOG="${CHATGW_LOG:-/tmp/chatserver-chatgw.log}"
INTERNAL_SECRET="${INTERNAL_SECRET:-dev-internal-secret-change-me}"
MINIO_BUCKET="${MINIO_BUCKET:-chat-files}"

PY_PID=""
GO_PID=""
TAIL_PID=""

cleanup() {
    echo
    echo "--- shutting down ---"
    # Order matters: Go gateway first (so in-flight WS reads fail fast), then Python.
    if [ -n "$GO_PID" ] && kill -0 "$GO_PID" 2>/dev/null; then
        kill "$GO_PID" 2>/dev/null || true
        wait "$GO_PID" 2>/dev/null || true
        echo "  chatgw (pid $GO_PID) stopped"
    fi
    if [ -n "$PY_PID" ] && kill -0 "$PY_PID" 2>/dev/null; then
        kill "$PY_PID" 2>/dev/null || true
        wait "$PY_PID" 2>/dev/null || true
        echo "  uvicorn (pid $PY_PID) stopped"
    fi
    if [ -n "$TAIL_PID" ] && kill -0 "$TAIL_PID" 2>/dev/null; then
        kill "$TAIL_PID" 2>/dev/null || true
    fi
    echo "  done."
}
trap cleanup EXIT INT TERM

cd "$PY_DIR"

echo "--- 1/5 docker compose up -d database minio ---"
docker compose up -d database minio >/dev/null

# Wait for postgres health (compose has a healthcheck; this just blocks until it flips).
echo "       waiting for postgres healthy..."
for _ in $(seq 1 30); do
    status="$(docker inspect -f '{{.State.Health.Status}}' database 2>/dev/null || true)"
    [ "$status" = "healthy" ] && break
    sleep 1
done
[ "${status:-}" = "healthy" ] || { echo "       postgres never became healthy" >&2; exit 1; }
echo "       postgres healthy"

# MinIO has a healthcheck too but is faster — short wait is plenty.
sleep 2
echo "       minio container running"

echo
echo "--- 2/5 alembic upgrade head ---"
uv run alembic upgrade head

echo
echo "--- 3/5 ensure MinIO bucket '$MINIO_BUCKET' ---"
# `mc mb` is idempotent with --ignore-existing.
docker exec minio mc alias set local http://localhost:9000 minioadmin minioadmin >/dev/null 2>&1 || true
docker exec minio mc mb --ignore-existing "local/$MINIO_BUCKET" >/dev/null

echo
echo "--- 4/5 start Python app ($PYTHON_LOG) ---"
: > "$PYTHON_LOG"
MINIO_ENDPOINT=localhost:9000 \
    INTERNAL_SECRET="$INTERNAL_SECRET" \
    nohup uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 > "$PYTHON_LOG" 2>&1 &
PY_PID=$!
echo "       uvicorn pid=$PY_PID"

# Wait for uvicorn to bind :8000.
for _ in $(seq 1 30); do
    if curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:8000/openapi.json" 2>/dev/null | grep -q "200"; then
        echo "       uvicorn healthy"
        break
    fi
    sleep 1
done

echo
echo "--- 5/5 build + start Go chatgw ($CHATGW_LOG) ---"
: > "$CHATGW_LOG"
CHATGW_BIN="/tmp/chatgw-dev"
# Pre-compile so the spawned process PID is the binary itself, not `go run`'s
# transient wrapper (whose child the trap cleanup can't reach).
(cd "$GO_DIR" && go build -o "$CHATGW_BIN" ./cmd/chatgw)
CHATGW_PYTHON_BASE_URL="http://127.0.0.1:8000" \
    CHATGW_INTERNAL_SECRET="$INTERNAL_SECRET" \
    nohup "$CHATGW_BIN" > "$CHATGW_LOG" 2>&1 &
GO_PID=$!
echo "       chatgw pid=$GO_PID  (PYTHON_BASE_URL=http://127.0.0.1:8000)"

# Wait for chatgw to bind :8080.
for _ in $(seq 1 30); do
    if ss -tln 2>/dev/null | grep -q ":8080 "; then
        echo "       chatgw listening"
        break
    fi
    sleep 1
done

echo
echo "=============================================="
echo "  Python REST : http://127.0.0.1:8000  (logs: $PYTHON_LOG)"
echo "  Go chatgw   : ws://127.0.0.1:8080/ws (logs: $CHATGW_LOG)"
echo "  Postgres    : localhost:5432   (db: ipd_db)"
echo "  MinIO       : http://127.0.0.1:9000  console: http://127.0.0.1:9001"
echo "=============================================="
echo "  Ctrl-C to stop both servers."
echo

# Live-tail both logs together. The tail process inherits the trap exit.
tail -F "$PYTHON_LOG" "$CHATGW_LOG" &
TAIL_PID=$!
wait "$TAIL_PID"
