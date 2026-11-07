from aiogram import Router
from .shop import router as shop_router
from .worker import router as worker_router
from .admin import router as admin_router
from .profile import router as profile_router
router = Router()
router.include_router(shop_router)
router.include_router(worker_router)
router.include_router(admin_router)
router.include_router(profile_router)
