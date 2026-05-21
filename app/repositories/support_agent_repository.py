from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.support_agent import SupportAgent


class SupportAgentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, *, login: str, password_hash: str, display_name: str) -> SupportAgent:
        agent = SupportAgent(login=login, password_hash=password_hash, display_name=display_name, is_active=True)
        self._session.add(agent)
        await self._session.flush()
        await self._session.refresh(agent)
        return agent

    async def get_by_id(self, agent_id: int) -> SupportAgent | None:
        row = await self._session.execute(select(SupportAgent).where(SupportAgent.id == agent_id))
        return row.scalar_one_or_none()

    async def get_by_login(self, login: str) -> SupportAgent | None:
        row = await self._session.execute(select(SupportAgent).where(SupportAgent.login == login))
        return row.scalar_one_or_none()

    async def list(self, *, active_only: bool, limit: int, offset: int) -> list[SupportAgent]:
        stmt = select(SupportAgent).order_by(SupportAgent.id).limit(limit).offset(offset)
        if active_only:
            stmt = stmt.where(SupportAgent.is_active.is_(True))
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())
