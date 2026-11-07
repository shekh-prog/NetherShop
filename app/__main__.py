import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ErrorEvent
from app.config import settings
from app.database import init_engine
from app.handlers import router
from app.middleware import AccessMiddleware

log = logging.getLogger("nethershop")

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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await init_engine()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.update.outer_middleware(AccessMiddleware())
    dp.errors.register(on_error)
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
