from fastapi import APIRouter

from app.api.routers.admin import router as admin_router
from app.api.routers.admin_audit_log import router as admin_audit_log_router
from app.api.routers.admin_managers import router as admin_managers_router
from app.api.routers.admin_partners import router as admin_partners_router
from app.api.routers.admin_reports import router as admin_reports_router
from app.api.routers.admin_users import router as admin_users_router
from app.api.routers.applications import router as applications_router
from app.api.routers.auth import router as auth_router
from app.api.routers.certificates import router as certificates_router
from app.api.routers.chats import router as chats_router
from app.api.routers.deals import router as deals_router
from app.api.routers.files import router as files_router
from app.api.routers.me import router as me_router
from app.api.routers.partners import router as partners_router
from app.api.routers.referrals import router as referrals_router
from app.api.routers.reports import router as reports_router
from app.api.routers.support import router as support_router
from app.api.routers.support_applications import router as support_applications_router
from app.api.routers.support_certificates import router as support_certificates_router
from app.api.routers.support_deals import router as support_deals_router
from app.api.routers.templates import router as templates_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(me_router)
api_router.include_router(referrals_router)
api_router.include_router(partners_router)
api_router.include_router(applications_router)
api_router.include_router(deals_router)
api_router.include_router(certificates_router)
api_router.include_router(chats_router)
api_router.include_router(files_router)
api_router.include_router(reports_router)
api_router.include_router(admin_router)
api_router.include_router(admin_users_router)
api_router.include_router(admin_managers_router)
api_router.include_router(admin_reports_router)
api_router.include_router(admin_audit_log_router)
api_router.include_router(admin_partners_router)
api_router.include_router(support_router)
api_router.include_router(support_applications_router)
api_router.include_router(support_certificates_router)
api_router.include_router(support_deals_router)
api_router.include_router(templates_router)
