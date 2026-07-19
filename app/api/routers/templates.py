from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps.subject_auth import SubjectRow, get_current_subject
from app.core.database import get_async_session
from app.models.tables.template_phrase import TemplatePhrase

router = APIRouter(prefix="/templates", tags=["templates"])

_VALID_SCOPES = {"user", "bonus", "support"}


class TemplatePhraseResponse(BaseModel):
    id: int
    scope: str
    text: str
    sort_order: int

    class Config:
        from_attributes = True


class TemplatePhraseCreate(BaseModel):
    scope: str = Field(..., description="'user' | 'bonus' | 'support'")
    text: str = Field(..., min_length=1, max_length=1000)
    sort_order: int = 0


@router.get("/", response_model=list[TemplatePhraseResponse])
async def list_templates(
    scope: str = Query(default="user"),
    session: AsyncSession = Depends(get_async_session),
) -> list[TemplatePhraseResponse]:
    """Список активных шаблонных фраз. Доступен без авторизации —
    фразы показываются и в виджете на лендинге."""
    if scope not in _VALID_SCOPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid scope")
    rows = await session.execute(
        select(TemplatePhrase)
        .where(TemplatePhrase.scope == scope, TemplatePhrase.is_active.is_(True))
        .order_by(TemplatePhrase.sort_order, TemplatePhrase.id)
    )
    return [TemplatePhraseResponse.model_validate(r) for r in rows.scalars().all()]


@router.post("/", response_model=TemplatePhraseResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplatePhraseCreate,
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> TemplatePhraseResponse:
    """Создание шаблона — только для менеджеров поддержки."""
    if subject.subject.type != "support" or subject.support is None or not subject.support.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="support only")
    if payload.scope not in _VALID_SCOPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid scope")
    row = TemplatePhrase(scope=payload.scope, text=payload.text.strip(), sort_order=payload.sort_order)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return TemplatePhraseResponse.model_validate(row)


@router.delete("/{template_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    if subject.subject.type != "support" or subject.support is None or not subject.support.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="support only")
    row = await session.get(TemplatePhrase, template_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="template not found")
    await session.delete(row)
    await session.commit()
