from fastapi import APIRouter, Depends, HTTPException, Query, status
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.admin_auth import admin_basic_auth
from app.core.database import get_async_session
from app.models.dto.support_agent import (
    SupportAgentCreate,
    SupportAgentResponse,
    SupportAgentUpdate,
)
from app.repositories.support_agent_repository import SupportAgentRepository


_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_basic_auth)])


class SupportAgentList(BaseModel):
    agents: list[SupportAgentResponse]


@router.post("/support-agents/", response_model=SupportAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_support_agent(
    payload: SupportAgentCreate,
    session: AsyncSession = Depends(get_async_session),
) -> SupportAgentResponse:
    repo = SupportAgentRepository(session)
    if await repo.get_by_login(payload.login) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="login already exists")
    try:
        agent = await repo.create(
            login=payload.login,
            password_hash=_pwd.hash(payload.password),
            display_name=payload.display_name,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="login already exists")
    return SupportAgentResponse.model_validate(agent, from_attributes=True)


@router.get("/support-agents/", response_model=SupportAgentList)
async def list_support_agents(
    active_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_async_session),
) -> SupportAgentList:
    repo = SupportAgentRepository(session)
    rows = await repo.list(active_only=active_only, limit=limit, offset=offset)
    return SupportAgentList(agents=[SupportAgentResponse.model_validate(a, from_attributes=True) for a in rows])


@router.patch("/support-agents/{agent_id}/", response_model=SupportAgentResponse)
async def patch_support_agent(
    agent_id: int,
    payload: SupportAgentUpdate,
    session: AsyncSession = Depends(get_async_session),
) -> SupportAgentResponse:
    repo = SupportAgentRepository(session)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if payload.password is not None:
        agent.password_hash = _pwd.hash(payload.password)
    if payload.display_name is not None:
        agent.display_name = payload.display_name
    if payload.is_active is not None:
        agent.is_active = payload.is_active
    await session.commit()
    await session.refresh(agent)
    return SupportAgentResponse.model_validate(agent, from_attributes=True)


@router.delete("/support-agents/{agent_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_support_agent(
    agent_id: int,
    session: AsyncSession = Depends(get_async_session),
) -> None:
    repo = SupportAgentRepository(session)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    agent.is_active = False
    await session.commit()
