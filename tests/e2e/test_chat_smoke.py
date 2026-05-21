"""End-to-end smoke for the full chat stack.

What this exercises (and what the unit + integration tests don't cover):
- Real WebSocket subprotocol auth handshake against the Go `chatgw` gateway
- Hub fan-out across two real connections in the same chat
- Round-trip persistence via `/internal/auth/ws-validate` + `/internal/chats/{id}/messages`
- File upload via REST + `send_file` envelope reference + downstream broadcast
- History endpoint matching the live persisted state

Run prerequisites (skipped automatically if anything is missing):
- Python app listening on http://127.0.0.1:8000 (matches `PYTHON_BASE`)
- Go chatgw listening on ws://127.0.0.1:8080/ws (matches `GO_WS_BASE`)
- Postgres + MinIO containers up; `chat-files` bucket created
- The Python app must be started with `MINIO_ENDPOINT=localhost:9000` if MinIO
  is exposed on the host (the in-container default `minio:9000` doesn't resolve
  from the host)
- `INTERNAL_SECRET` agrees between the Python app and the Go gateway

Run:
    uv run pytest tests/e2e/ -v
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import uuid

import httpx
import pytest
import websockets


PYTHON_BASE = "http://127.0.0.1:8000"
GO_WS_BASE = "ws://127.0.0.1:8080/ws"
ADMIN_LOGIN = "admin"
ADMIN_PASSWORD = "admin"
SUPPORT_LOGIN = "e2e-support"
SUPPORT_PASSWORD = "e2e-support-pw"


def _tcp_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not (_tcp_port_open("127.0.0.1", 8000) and _tcp_port_open("127.0.0.1", 8080)),
    reason="e2e requires Python (:8000) and Go chatgw (:8080) servers running",
)


async def _ensure_support_agent() -> str:
    """Idempotently create the e2e support agent and return a login JWT."""
    async with httpx.AsyncClient(base_url=PYTHON_BASE) as c:
        create = await c.post(
            "/api/v1/admin/support-agents/",
            json={"login": SUPPORT_LOGIN, "password": SUPPORT_PASSWORD, "display_name": "E2E Support"},
            auth=(ADMIN_LOGIN, ADMIN_PASSWORD),
        )
        if create.status_code not in (201, 409):
            create.raise_for_status()

        login = await c.post(
            "/api/v1/support/login/",
            json={"login": SUPPORT_LOGIN, "password": SUPPORT_PASSWORD},
        )
        login.raise_for_status()
        return login.json()["access_token"]


async def _seed_customer() -> tuple[int, str]:
    """Insert a fresh customer directly via raw asyncpg and mint a JWT.

    Goes around the conftest-influenced ORM session — the root `tests/conftest.py`
    pins `DB_NAME=insurance_platform_test` for the per-test rollback fixture, but
    the running app uses the dev DB (`ipd_db`). We hit the dev DB directly so the
    seeded user is visible to the running uvicorn.

    Reads connection params from `app.core.config.settings` for host/user/password
    (those aren't overridden by conftest), but uses the dev DB name explicitly.
    """
    # Import lazily so `pytest --collect-only` doesn't require the live DB.
    import asyncpg
    from datetime import datetime, timedelta
    from jose import jwt as jose_jwt

    from app.core.config import settings

    db_name = os.environ.get("E2E_DB_NAME", "ipd_db")
    conn = await asyncpg.connect(
        host=settings.db_host, port=settings.db_port,
        user=settings.db_user, password=settings.db_password,
        database=db_name,
    )
    try:
        suffix = uuid.uuid4().hex[:6]
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, phone, password_hash, first_name, last_name,
                               patronymic, balance, pending_balance, referral_code,
                               referrer_id, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, NULL, 0, 0, $6, NULL, now(), now())
            RETURNING id
            """,
            f"e2e-{suffix}@example.com",
            f"+15{int(uuid.uuid4().int % 1_000_000_000):010d}",
            "$2b$12$placeholder",
            "E2E", "Test",
            f"E2E{suffix.upper()}"[:16],
        )
        user_id = row["id"]
    finally:
        await conn.close()

    now = datetime.utcnow()
    payload = {
        "user_id": user_id,
        "sub": f"user:{user_id}",
        "role": "user",
        "type": "access",
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
        "iat": now,
    }
    token = jose_jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return user_id, token


async def _open_ws(token: str, chat_type: str, chat_id_hint: str = ""):
    url = f"{GO_WS_BASE}?type={chat_type}"
    if chat_id_hint:
        url += f"&chat_id={chat_id_hint}"
    return await websockets.connect(
        url,
        subprotocols=[f"chatgw.token.{token}", "chatgw.v1"],
        open_timeout=5,
    )


@pytest.mark.asyncio
async def test_full_chat_round_trip():
    # 1. Tokens.
    customer_id, customer_token = await _seed_customer()
    support_token = await _ensure_support_agent()

    # 2. Lazy-create main chat via REST.
    async with httpx.AsyncClient(base_url=PYTHON_BASE) as c:
        r = await c.get("/api/v1/chats/", headers={"Authorization": f"Bearer {customer_token}"})
        r.raise_for_status()
        chat_id = next(ch["id"] for ch in r.json() if ch["type"] == "main")

    # 3. Open WS as both parties.
    customer_ws = await _open_ws(customer_token, "main")
    support_ws = await _open_ws(support_token, "main", chat_id_hint=chat_id)

    try:
        # 4. Customer → support text fan-out.
        cli_msg = {"type": "send_message", "client_msg_id": "e2e-cli-1", "body": "hello support"}
        await customer_ws.send(json.dumps(cli_msg))
        customer_text = json.loads(await asyncio.wait_for(customer_ws.recv(), timeout=5))
        support_text = json.loads(await asyncio.wait_for(support_ws.recv(), timeout=5))
        assert customer_text["type"] == "message"
        assert customer_text["message"]["body"] == "hello support"
        assert customer_text["message"]["client_msg_id"] == "e2e-cli-1"
        assert customer_text["message"]["user_id"] == f"user:{customer_id}"
        assert support_text["message"]["id"] == customer_text["message"]["id"]

        # 5. Support → customer reply.
        spt_msg = {"type": "send_message", "client_msg_id": "e2e-spt-1", "body": "hi customer"}
        await support_ws.send(json.dumps(spt_msg))
        support_echo = json.loads(await asyncio.wait_for(support_ws.recv(), timeout=5))
        customer_echo = json.loads(await asyncio.wait_for(customer_ws.recv(), timeout=5))
        assert customer_echo["message"]["body"] == "hi customer"
        assert customer_echo["message"]["role"] == "support"
        assert support_echo["message"]["id"] == customer_echo["message"]["id"]

        # 6. Idempotent retry — same client_msg_id returns same id.
        await customer_ws.send(json.dumps(cli_msg))
        retry_customer = json.loads(await asyncio.wait_for(customer_ws.recv(), timeout=5))
        # The Go gateway broadcasts on every persist, including idempotent ones,
        # so the support side will also see a duplicate. Drain it to keep the queue clean.
        await asyncio.wait_for(support_ws.recv(), timeout=5)
        assert retry_customer["message"]["id"] == customer_text["message"]["id"]

        # 7. File upload via REST + send_file via WS.
        async with httpx.AsyncClient(base_url=PYTHON_BASE) as c:
            up = await c.post(
                "/api/v1/files/",
                files={"file": ("e2e.txt", b"e2e payload", "text/plain")},
                data={"chat_id": chat_id},
                headers={"Authorization": f"Bearer {customer_token}"},
            )
            up.raise_for_status()
            file_meta = up.json()
        assert file_meta["name"] == "e2e.txt"
        assert file_meta["mime"] == "text/plain"
        assert file_meta["size"] == 11

        file_env = {"type": "send_file", "client_msg_id": "e2e-file-1", "file_id": file_meta["file_id"]}
        await customer_ws.send(json.dumps(file_env))
        customer_file = json.loads(await asyncio.wait_for(customer_ws.recv(), timeout=5))
        support_file = json.loads(await asyncio.wait_for(support_ws.recv(), timeout=5))
        assert customer_file["type"] == "file"
        assert customer_file["message"]["kind"] == "file"
        assert customer_file["message"]["file"]["file_id"] == file_meta["file_id"]
        assert customer_file["message"]["file"]["name"] == "e2e.txt"
        assert support_file["message"]["id"] == customer_file["message"]["id"]

        # 8. History endpoint matches what we sent: 3 messages, newest first.
        async with httpx.AsyncClient(base_url=PYTHON_BASE) as c:
            h = await c.get(
                f"/api/v1/chats/{chat_id}/messages/?limit=10",
                headers={"Authorization": f"Bearer {customer_token}"},
            )
            h.raise_for_status()
            history = h.json()
        assert len(history["messages"]) == 3
        kinds_and_bodies = [(m["kind"], m.get("body"), (m.get("file") or {}).get("name")) for m in history["messages"]]
        assert kinds_and_bodies[0] == ("file", None, "e2e.txt")
        assert kinds_and_bodies[1] == ("message", "hi customer", None)
        assert kinds_and_bodies[2] == ("message", "hello support", None)
    finally:
        await customer_ws.close()
        await support_ws.close()
