import asyncio
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
    try:
        if update.callback_query:
            await update.callback_query.answer("Что-то пошло не так. Попробуй ещё раз.", show_alert=True)
        elif update.message:
            await update.message.answer("Что-то пошло не так. Попробуй ещё раз.")
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
