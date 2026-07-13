from fastapi import APIRouter

from app.api.admin import dashboard, eval, kb, settings, users

router = APIRouter(prefix="/admin")
router.include_router(users.router)
router.include_router(settings.router)
router.include_router(kb.router)
router.include_router(eval.router)
router.include_router(dashboard.router)
