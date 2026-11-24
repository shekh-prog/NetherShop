from aiogram import Router
from .shop import router as shop_router
from .worker import router as worker_router
from .admin import router as admin_router
from .profile import router as profile_router
from .promo import router as promo_router, admin_router as promo_admin_router
from .editor import router as editor_router
router = Router()
router.include_router(shop_router)
router.include_router(worker_router)
router.include_router(admin_router)
router.include_router(profile_router)
router.include_router(promo_router)
router.include_router(promo_admin_router)
router.include_router(editor_router)
