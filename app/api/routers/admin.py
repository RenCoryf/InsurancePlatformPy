import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.manager_auth import get_current_admin
from app.api.deps.redis_dep import get_redis
from app.api.deps.subject_auth import SubjectRow
from app.core.config import settings
from app.core.database import get_async_session
from app.models.audit_log import AuditLog
from app.models.dto.admin import (
    BlockUserRequest,
    RootReferralResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    UserDeleteConfirmationResponse,
    UserStatusResponse,
)
from app.models.dto.support_agent import (
    ManagerCreateRequest,
    ManagerInviteResponse,
    SupportAgentCreate,
    SupportAgentResponse,
    SupportAgentUpdate,
)
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from app.models.users.refresh_token import RefreshToken
from app.repositories.support_agent_repository import SupportAgentRepository
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.referral_service import ReferralService
from app.services.settings_service import SettingsService
from app.services.sms_service import SMSService_SMSC

logger = logging.getLogger(__name__)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

DELETE_CONFIRM_TTL_SECONDS = 5 * 60

router = APIRouter(prefix="/admin", tags=["admin"])


class SupportAgentList(BaseModel):
    agents: list[SupportAgentResponse]


def _agent_response(agent: SupportAgent) -> SupportAgentResponse:
    return SupportAgentResponse.model_validate(agent, from_attributes=True)


async def _revoke_user_refresh_tokens(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.is_revoked == False)
        .values(is_revoked=True)
    )


async def _send_invite_sms(session: AsyncSession, phone: str, invite_link: str) -> None:
    """Отправка SMS-приглашения. Ошибка доставки не срывает создание —
    ссылку можно передать вручную, она есть в ответе API.

    Менеджер не привязан к User, поэтому отправка идёт напрямую через
    SMSService, минуя очередь; текст — из шаблона ``manager_invite``.
    """
    message = await NotificationService(session).render_template(
        "manager_invite", {"link": invite_link}
    )
    if not (settings.smsc_login and settings.smsc_password):
        logger.info("SMSC is not configured; invite for %s: %s", phone, invite_link)
        return
    sms = SMSService_SMSC.with_credentials(
        username=settings.smsc_login,
        password=settings.smsc_password,
        lk_url=settings.sms_lk_url,
    )
    try:
        await sms.send_message(phone, message)
    except Exception:
        logger.exception("Failed to send invite SMS to %s", phone)


# ---------------------------------------------------------------------------
# Support agents (менеджеры/администраторы)
# ---------------------------------------------------------------------------


@router.post("/support-agents/", response_model=SupportAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_support_agent(
    payload: SupportAgentCreate,
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
) -> SupportAgentResponse:
    repo = SupportAgentRepository(session)
    if await repo.get_by_login(payload.login) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="login already exists")
    audit = AuditService(session)
    try:
        agent = await repo.create(
            login=payload.login,
            password_hash=_pwd.hash(payload.password),
            display_name=payload.display_name,
        )
        await session.flush()
        await audit.log(
            performed_by_type=AuditLog.BY_ADMIN,
            performed_by_id=admin.support.id,
            action=AuditLog.ACTION_MANAGER_CREATE,
            target_type=AuditLog.TARGET_MANAGER,
            target_id=agent.id,
            new_value={"login": agent.login, "role": agent.role},
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="login already exists")
    return _agent_response(agent)


@router.post("/managers/", response_model=ManagerInviteResponse, status_code=status.HTTP_201_CREATED)
async def create_manager_with_invite(
    payload: ManagerCreateRequest,
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
) -> ManagerInviteResponse:
    """Создать менеджера/администратора и отправить SMS-приглашение.

    Пароль не задаётся: до перехода по инвайт-ссылке у записи стоит
    случайный неизвестный никому хеш, вход невозможен.
    """
    if payload.role == SupportAgent.ROLE_ADMIN and not admin.support.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the owner can create admins",
        )

    existing = await session.execute(
        select(SupportAgent).where(
            (SupportAgent.login == payload.login) | (SupportAgent.phone == payload.phone)
        )
    )
    if existing.scalars().first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="login or phone already exists")

    invite_token = secrets.token_urlsafe(32)
    invite_expires_at = datetime.utcnow() + timedelta(hours=settings.support_invite_ttl_hours)

    agent = SupportAgent(
        login=payload.login,
        password_hash=_pwd.hash(secrets.token_urlsafe(32)),
        display_name=payload.display_name,
        role=payload.role,
        permissions=payload.permissions,
        phone=payload.phone,
        invited_by_admin_id=admin.support.id,
        invite_token=invite_token,
        invite_expires_at=invite_expires_at,
    )
    session.add(agent)

    audit = AuditService(session)
    try:
        await session.flush()
        is_admin_role = payload.role == SupportAgent.ROLE_ADMIN
        await audit.log(
            performed_by_type=AuditLog.BY_ADMIN,
            performed_by_id=admin.support.id,
            action=AuditLog.ACTION_ADMIN_CREATE if is_admin_role else AuditLog.ACTION_MANAGER_CREATE,
            target_type=AuditLog.TARGET_ADMIN if is_admin_role else AuditLog.TARGET_MANAGER,
            target_id=agent.id,
            new_value={
                "login": agent.login,
                "role": agent.role,
                "permissions": agent.permissions,
                "phone": agent.phone,
            },
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="login or phone already exists")
    await session.refresh(agent)

    invite_link = f"{settings.invite_link_base_url.rstrip('/')}/invite/{invite_token}"
    await _send_invite_sms(session, agent.phone, invite_link)

    return ManagerInviteResponse(
        agent=_agent_response(agent),
        invite_token=invite_token,
        invite_expires_at=invite_expires_at,
        invite_link=invite_link,
    )


@router.get("/support-agents/", response_model=SupportAgentList)
async def list_support_agents(
    active_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> SupportAgentList:
    repo = SupportAgentRepository(session)
    rows = await repo.list(active_only=active_only, limit=limit, offset=offset)
    return SupportAgentList(agents=[_agent_response(a) for a in rows])


@router.patch("/support-agents/{agent_id}/", response_model=SupportAgentResponse)
async def patch_support_agent(
    agent_id: int,
    payload: SupportAgentUpdate,
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
) -> SupportAgentResponse:
    repo = SupportAgentRepository(session)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if payload.is_active is False and agent.is_owner:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="cannot deactivate the owner")

    if payload.password is not None:
        agent.password_hash = _pwd.hash(payload.password)
    if payload.display_name is not None:
        agent.display_name = payload.display_name
    if payload.is_active is not None:
        agent.is_active = payload.is_active
    if payload.permissions is not None and payload.permissions != (agent.permissions or []):
        old_permissions = list(agent.permissions or [])
        agent.permissions = payload.permissions
        await AuditService(session).log(
            performed_by_type=AuditLog.BY_ADMIN,
            performed_by_id=admin.support.id,
            action=AuditLog.ACTION_PERMISSION_CHANGE,
            target_type=AuditLog.TARGET_MANAGER,
            target_id=agent.id,
            old_value={"permissions": old_permissions},
            new_value={"permissions": payload.permissions},
        )
    await session.commit()
    await session.refresh(agent)
    return _agent_response(agent)


@router.delete("/support-agents/{agent_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_support_agent(
    agent_id: int,
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> None:
    repo = SupportAgentRepository(session)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if agent.is_owner:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="cannot deactivate the owner")
    agent.is_active = False
    await session.commit()


# ---------------------------------------------------------------------------
# Модерация пользователей
# ---------------------------------------------------------------------------


async def _get_user_or_404(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


@router.post("/users/{user_id}/block/", response_model=UserStatusResponse)
async def block_user(
    user_id: int,
    payload: BlockUserRequest,
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
    redis=Depends(get_redis),
) -> UserStatusResponse:
    user = await _get_user_or_404(session, user_id)
    if user.status == User.STATUS_DELETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="user is deleted")
    if user.status == User.STATUS_BLOCKED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="user is already blocked")

    old_status = user.status
    user.status = User.STATUS_BLOCKED
    user.blocked_reason = payload.reason
    user.blocked_comment = payload.comment
    user.blocked_at = datetime.utcnow()
    user.blocked_by_admin_id = admin.support.id
    await _revoke_user_refresh_tokens(session, user.id)

    await AuditService(session).log(
        performed_by_type=AuditLog.BY_ADMIN,
        performed_by_id=admin.support.id,
        action=AuditLog.ACTION_USER_BLOCK,
        target_type=AuditLog.TARGET_USER,
        target_id=user.id,
        old_value={"status": old_status},
        new_value={"status": User.STATUS_BLOCKED, "reason": payload.reason},
        comment=payload.comment,
    )
    await session.commit()
    await ReferralService(session, redis).invalidate_upline_cache(user.id)
    await session.refresh(user)
    return UserStatusResponse.model_validate(user)


@router.post("/users/{user_id}/unblock/", response_model=UserStatusResponse)
async def unblock_user(
    user_id: int,
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
    redis=Depends(get_redis),
) -> UserStatusResponse:
    user = await _get_user_or_404(session, user_id)
    if user.status != User.STATUS_BLOCKED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="user is not blocked")

    old_reason = user.blocked_reason
    user.status = User.STATUS_ACTIVE
    user.blocked_reason = None
    user.blocked_comment = None
    user.blocked_at = None
    user.blocked_by_admin_id = None

    await AuditService(session).log(
        performed_by_type=AuditLog.BY_ADMIN,
        performed_by_id=admin.support.id,
        action=AuditLog.ACTION_USER_UNBLOCK,
        target_type=AuditLog.TARGET_USER,
        target_id=user.id,
        old_value={"status": User.STATUS_BLOCKED, "reason": old_reason},
        new_value={"status": User.STATUS_ACTIVE},
    )
    await session.commit()
    await ReferralService(session, redis).invalidate_upline_cache(user.id)
    await session.refresh(user)
    return UserStatusResponse.model_validate(user)


def _make_delete_confirm_token(user_id: int, admin_id: int) -> str:
    payload = {
        "action": "user_delete",
        "user_id": user_id,
        "admin_id": admin_id,
        "type": "confirm",
        "exp": datetime.utcnow() + timedelta(seconds=DELETE_CONFIRM_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _check_delete_confirm_token(token: str, user_id: int) -> None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid or expired confirm_token",
        )
    if payload.get("action") != "user_delete" or payload.get("type") != "confirm" or payload.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm_token does not match this user")


@router.delete("/users/{user_id}/")
async def delete_user(
    user_id: int,
    confirm_token: str | None = Query(default=None),
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
    redis=Depends(get_redis),
):
    """Удаление пользователя с двойным подтверждением.

    Первый вызов (без confirm_token) возвращает токен подтверждения;
    повторный вызов с токеном анонимизирует пользователя.
    """
    user = await _get_user_or_404(session, user_id)
    if user.status == User.STATUS_DELETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="user is already deleted")

    if confirm_token is None:
        return UserDeleteConfirmationResponse(
            confirm_token=_make_delete_confirm_token(user.id, admin.support.id),
            expires_in=DELETE_CONFIRM_TTL_SECONDS,
        )

    _check_delete_confirm_token(confirm_token, user.id)

    old_status = user.status
    user.status = User.STATUS_DELETED
    user.first_name = f"Удалённый пользователь #{user.id}"
    user.last_name = None
    user.patronymic = None
    user.phone = None
    user.email = None
    await _revoke_user_refresh_tokens(session, user.id)

    await AuditService(session).log(
        performed_by_type=AuditLog.BY_ADMIN,
        performed_by_id=admin.support.id,
        action=AuditLog.ACTION_USER_DELETE,
        target_type=AuditLog.TARGET_USER,
        target_id=user.id,
        old_value={"status": old_status},
        new_value={"status": User.STATUS_DELETED, "anonymized": True},
    )
    await session.commit()
    await ReferralService(session, redis).invalidate_upline_cache(user.id)
    await session.refresh(user)
    return UserStatusResponse.model_validate(user)


# ---------------------------------------------------------------------------
# Настройки платформы и корневая реферальная ссылка
# ---------------------------------------------------------------------------


@router.get("/settings/", response_model=SettingsResponse)
async def get_settings(
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> SettingsResponse:
    row = await SettingsService(session).get()
    return SettingsResponse.model_validate(row)


@router.patch("/settings/", response_model=SettingsResponse)
async def update_settings(
    payload: SettingsUpdateRequest,
    session: AsyncSession = Depends(get_async_session),
    redis=Depends(get_redis),
    admin: SubjectRow = Depends(get_current_admin),
) -> SettingsResponse:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no fields to update")

    svc = SettingsService(session, redis)
    row = await svc.get()
    old_values = SettingsService.as_dict(row)

    await AuditService(session).log(
        performed_by_type=AuditLog.BY_ADMIN,
        performed_by_id=admin.support.id,
        action=AuditLog.ACTION_SETTINGS_UPDATE,
        target_type=AuditLog.TARGET_SETTINGS,
        target_id="platform",
        old_value={k: old_values[k] for k in changes},
        new_value={k: (str(v) if v is not None else None) for k, v in changes.items()},
    )
    try:
        row = await svc.update(changes)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return SettingsResponse.model_validate(row)


def _root_referral_response(row) -> RootReferralResponse:
    link = None
    if row.root_referral_code and row.root_referral_active:
        link = f"{settings.referral_link_base_url.rstrip('/')}/{row.root_referral_code}"
    return RootReferralResponse(
        root_referral_code=row.root_referral_code,
        root_referral_active=row.root_referral_active,
        root_referral_link=link,
    )


@router.post("/settings/root-referral/generate/", response_model=RootReferralResponse)
async def generate_root_referral(
    session: AsyncSession = Depends(get_async_session),
    redis=Depends(get_redis),
    admin: SubjectRow = Depends(get_current_admin),
) -> RootReferralResponse:
    svc = SettingsService(session, redis)
    row = await svc.get()
    old_code = row.root_referral_code

    await AuditService(session).log(
        performed_by_type=AuditLog.BY_ADMIN,
        performed_by_id=admin.support.id,
        action=AuditLog.ACTION_SETTINGS_UPDATE,
        target_type=AuditLog.TARGET_SETTINGS,
        target_id="root_referral",
        old_value={"root_referral_code": old_code},
        new_value={"root_referral_active": True},
        comment="generate root referral code",
    )
    row = await svc.generate_root_referral()
    return _root_referral_response(row)


@router.post("/settings/root-referral/revoke/", response_model=RootReferralResponse)
async def revoke_root_referral(
    session: AsyncSession = Depends(get_async_session),
    redis=Depends(get_redis),
    admin: SubjectRow = Depends(get_current_admin),
) -> RootReferralResponse:
    svc = SettingsService(session, redis)
    row = await svc.get()
    old_code = row.root_referral_code

    await AuditService(session).log(
        performed_by_type=AuditLog.BY_ADMIN,
        performed_by_id=admin.support.id,
        action=AuditLog.ACTION_SETTINGS_UPDATE,
        target_type=AuditLog.TARGET_SETTINGS,
        target_id="root_referral",
        old_value={"root_referral_code": old_code},
        new_value={"root_referral_code": None, "root_referral_active": False},
        comment="revoke root referral code",
    )
    row = await svc.revoke_root_referral()
    return _root_referral_response(row)
