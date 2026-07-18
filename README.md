## Local run (without docker)

```bash
# 1. Postgres + Redis on localhost, DB created:
#    psql -U postgres -c "CREATE DATABASE insurance_platform;"
# 2. .env with DB_HOST=localhost, REDIS_HOST=localhost (see repo .env)
uv run python -m alembic upgrade head
uv run python scripts/seed_templates.py   # template phrases (idempotent)
./scripts/run-local.sh                    # serves http://127.0.0.1:8000
```

New endpoints (2026-07-18):
- `POST /api/v1/chats/{chat_id}/messages/` — REST-отправка текстового сообщения (без Go-шлюза)
- `DELETE /api/v1/chats/{chat_id}/messages/{message_id}/` — удаление сообщения (user — только свои, support — любые)
- `GET /api/v1/templates/?scope=user|bonus|support` — шаблонные фразы (публично)
- `POST/DELETE /api/v1/templates/…` — управление шаблонами (только support)
- `GET /api/v1/auth/debug-code/?phone=…` — dev-only: текущий OTP из Redis (404 в production)

## Chat smoke test (manual)

```bash
# 1. Infra
docker compose up -d database minio

# 2. Run migrations against the dev DB
uv run alembic upgrade head

# 3. Start the app
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. (In another terminal) Seed a support agent
curl -u admin:admin -X POST http://localhost:8000/api/v1/admin/support-agents/ \
  -H 'Content-Type: application/json' \
  -d '{"login":"alice","password":"changeme","display_name":"Alice"}'

# 5. (In another terminal) Bring up the Go gateway
cd ../InsurancePlatform
INTERNAL_SECRET="dev-internal-secret-change-me" \
PYTHON_BASE_URL=http://localhost:8000 \
go run ./cmd/chatgw

# 6. Use any WS client to:
#    - register a customer via existing /api/v1/auth/ endpoints, get a JWT
#    - open ws://localhost:8080/ws?type=main with the JWT subprotocol
#    - POST /api/v1/support/login/ to get a support JWT
#    - GET /api/v1/support/chats/ to find the chat_id
#    - open ws://localhost:8080/ws?type=main&chat_id=<id> as support
#    - send/receive text and file messages in both 'main' and 'bonus' chats
```

(The exact env var names in the Go process may differ — check `cmd/chatgw/main.go` for current names.)
