import asyncio
import html
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ErrorEvent
from app.config import settings
from app.database import init_engine
from app.fsm_storage import DbStorage
from app.handlers import router
from app.handlers.common import get_user
from app.middleware import AccessMiddleware

log = logging.getLogger("nethershop")
ROOT = Path(__file__).resolve().parent.parent

def run_migrations() -> None:
    """Применяет миграции Alembic до head. Безопасно вызывать при каждом старте."""
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")

async def on_error(event: ErrorEvent):
    # Раньше любое исключение просто терялось, и бот «молчал».
    log.exception("Ошибка при обработке апдейта", exc_info=event.exception)
    update = event.update
    exc = event.exception
    try:
        actor = update.callback_query.from_user if update.callback_query else (
            update.message.from_user if update.message else None)
        user = await get_user(actor.id) if actor else None
        is_admin = bool(actor and (actor.id == settings.admin_id or (user and user.role == "admin")))
        # Главам показываем, что именно сломалось, чтобы ошибку можно было сразу переслать разработчику.
        detail = f"{type(exc).__name__}: {exc}"
        if update.callback_query:
            text = "Что-то пошло не так. Попробуй ещё раз."
            if is_admin:
                text = (text + "\n" + detail)[:200]   # лимит текста alert — 200 символов
            await update.callback_query.answer(text, show_alert=True)
        elif update.message:
            text = "Что-то пошло не так. Попробуй ещё раз."
            if is_admin:
                text += f"\n\n<code>{html.escape(detail[:500])}</code>"
            await update.message.answer(text)
    except Exception:
        pass
    return True

async def main():
    # env.py Alembic сам запускает event loop (asyncio.run), поэтому миграции идут в отдельном потоке.
    await asyncio.to_thread(run_migrations)
    # Настройка логов — после миграций: Alembic перенастраивает logging по alembic.ini.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)
    log.info("Миграции применены")
    await init_engine()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=DbStorage())
    dp.update.outer_middleware(AccessMiddleware())
    dp.errors.register(on_error)
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
