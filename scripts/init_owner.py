"""Создание первого администратора-владельца (запускается один раз при деплое).

    OWNER_LOGIN=owner OWNER_PASSWORD='...' [OWNER_PHONE=79990000000] \
        uv run python -m scripts.init_owner

Идемпотентен: если владелец уже существует — ничего не делает.
Временный пароль передаётся через переменную окружения OWNER_PASSWORD
и должен быть сменён после первого входа.
"""
from __future__ import annotations

import asyncio
import sys

import dotenv
from passlib.context import CryptContext
from sqlalchemy import select

dotenv.load_dotenv()

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.tables.support_agent import SupportAgent  # noqa: E402

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def init_owner() -> int:
    login = settings.owner_login
    password = settings.owner_password
    if not password:
        print("OWNER_PASSWORD is not set — refusing to create the owner", file=sys.stderr)
        return 1

    async with AsyncSessionLocal() as session:
        existing_owner = await session.execute(
            select(SupportAgent).where(SupportAgent.is_owner.is_(True))
        )
        owner = existing_owner.scalars().first()
        if owner is not None:
            print(f"Owner already exists: id={owner.id} login={owner.login!r} — nothing to do")
            return 0

        existing_login = await session.execute(
            select(SupportAgent).where(SupportAgent.login == login)
        )
        if existing_login.scalar_one_or_none() is not None:
            print(f"Login {login!r} is already taken by a non-owner agent", file=sys.stderr)
            return 1

        owner = SupportAgent(
            login=login,
            password_hash=_pwd.hash(password),
            display_name="Owner",
            role=SupportAgent.ROLE_ADMIN,
            is_owner=True,
            phone=settings.owner_phone,
            permissions=[],
        )
        session.add(owner)
        await session.commit()
        await session.refresh(owner)
        print(f"Owner created: id={owner.id} login={owner.login!r} (role=admin, is_owner=True)")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(init_owner()))
