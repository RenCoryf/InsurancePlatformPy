from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_async_session
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User


SubjectType = Literal["user", "support"]


@dataclass(frozen=True)
class Subject:
    type: SubjectType
    id: int


@dataclass(frozen=True)
class SubjectRow:
    """Resolved subject — type/id plus the row from the matching table."""
    subject: Subject
    user: User | None = None
    support: SupportAgent | None = None


def parse_subject_claim(value: str) -> Subject:
    """Parse `"user:42"` / `"support:7"`. Raises ValueError on anything else."""
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"malformed sub claim: {value!r}")
    kind, raw_id = parts
    if kind not in ("user", "support"):
        raise ValueError(f"unknown subject kind: {kind!r}")
    if not raw_id:
        raise ValueError("subject id missing")
    try:
        sid = int(raw_id)
    except ValueError as e:
        raise ValueError(f"subject id not an integer: {raw_id!r}") from e
    return Subject(type=kind, id=sid)


_bearer = HTTPBearer(auto_error=False)


def _credentials_exception(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_subject(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_async_session),
) -> SubjectRow:
    if credentials is None:
        raise _credentials_exception("missing bearer token")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise _credentials_exception(str(e))
    sub_claim = payload.get("sub")
    if not isinstance(sub_claim, str):
        raise _credentials_exception("missing sub claim")
    try:
        subject = parse_subject_claim(sub_claim)
    except ValueError as e:
        raise _credentials_exception(str(e))

    if subject.type == "user":
        row = await session.execute(select(User).where(User.id == subject.id))
        user = row.scalar_one_or_none()
        if user is None:
            raise _credentials_exception("user not found")
        return SubjectRow(subject=subject, user=user)
    else:
        row = await session.execute(select(SupportAgent).where(SupportAgent.id == subject.id))
        support = row.scalar_one_or_none()
        if support is None or not support.is_active:
            raise _credentials_exception("support agent not found or inactive")
        return SubjectRow(subject=subject, support=support)
