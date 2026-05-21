import pytest
from jose import jwt
from sqlalchemy import select

from app.core.config import settings
from app.models.users.entities import User
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_user_access_token_carries_sub_and_role(db_session):
    svc = AuthService(db_session)
    token = svc._generate_access_token(user_id=1234)
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["user_id"] == 1234
    assert payload["sub"] == "user:1234"
    assert payload["role"] == "user"
    assert payload["type"] == "access"
