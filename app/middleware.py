from datetime import datetime
from aiogram import BaseMiddleware
from aiogram.types import Update
from sqlalchemy import select
from app.database import Session
from app.models import User
from app.states import Registration
from app.utils import NICK_PLACEHOLDER, utcnow

# Постоянный бан хранится как «очень далёкая дата» (None = не забанен).
PERMANENT_BAN = datetime(9999, 12, 31, 23, 59, 59)

MENU_TEXTS = {"Сделать заказ", "Мои заказы", "Профиль", "Выполнить заказ",
              "Кастомизировать", "Кастомизииировать", "Статистика"}

def _is_start(text: str | None) -> bool:
    return bool(text) and text.split()[0].split("@")[0] == "/start"

class AccessMiddleware(BaseMiddleware):
    """Бан, обязательная регистрация и сброс «зависших» FSM-состояний."""

    async def __call__(self, handler, event: Update, data: dict):
        call = event.callback_query
        message = event.message
        actor = call.from_user if call else (message.from_user if message else None)
        if actor is None or actor.is_bot:
            return await handler(event, data)

        async with Session() as s:
            user = (await s.execute(select(User).where(User.telegram_id == actor.id))).scalar_one_or_none()
            if user:
                changed = False
                # Держим @username актуальным, чтобы /list всегда давал рабочие ссылки.
                if user.telegram_username != actor.username:
                    user.telegram_username = actor.username
                    changed = True
                if user.banned_until is not None and user.banned_until <= utcnow():
                    user.banned_until = None
                    changed = True
                if changed:
                    await s.commit()

        async def refuse(text: str):
            if call:
                await call.answer(text, show_alert=True)
            elif message:
                await message.answer(text)

        if user and user.banned_until is not None and user.role != "admin":
            await refuse("Доступ к NetherShop заблокирован. Обратись к администрации.")
            return None

        text = message.text if message else None
        raw_state = data.get("raw_state")
        registered = user is not None and user.minecraft_nick != NICK_PLACEHOLDER
        if not registered:
            # Не зарегистрирован (или удалён командой /delete): пускаем только на /start и ввод ника.
            if not _is_start(text) and raw_state != Registration.minecraft_nick.state:
                await refuse("Сначала зарегистрируйся: отправь /start.")
                return None
        elif raw_state and text and (text.startswith("/") or text in MENU_TEXTS):
            # Команда или кнопка меню посреди диалога — выходим из диалога,
            # иначе текст команды уйдёт в обработчик шага (например, как название товара).
            state = data.get("state")
            if state:
                await state.clear()
                data["raw_state"] = None  # фильтры состояний читают закэшированное значение
        return await handler(event, data)

# Старое имя оставлено для совместимости.
BanMiddleware = AccessMiddleware
