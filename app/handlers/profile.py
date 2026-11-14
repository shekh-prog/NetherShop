from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func
from app.database import Session
from app.models import User, Sale
from app.handlers.common import get_user, nick_taken, sync_head_protection
from app.states import ProfileFlow
from app.keyboards import profile_kb, nick_confirm_kb, nick_cancel_kb, main_menu
from app.services.orders import user_debt
from app.utils import safe, price_text, valid_nick, NICK_RULES
from app.branding import send_branded, edit_branded, remember, show

router = Router()

@router.message(F.text == "Профиль")
async def profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся через /start.")
        return
    async with Session() as s:
        spent = await s.scalar(select(func.coalesce(func.sum(Sale.total_diamonds), 0)).where(Sale.user_id == user.id))
    debt, debt_count = await user_debt(user.id)
    debt_line = (f"\n💎 Долг (оставить в сундуке с заказом): <b>{price_text(debt)}</b> · заказов: {debt_count}"
                 if debt else "")
    await send_branded(message,
        f"<b>Твой профиль</b>\nMinecraft-ник: <b>{safe(user.minecraft_nick)}</b>\nПотрачено за всё время: <b>{price_text(int(spent or 0))}</b>{debt_line}",
        reply_markup=profile_kb())

@router.callback_query(F.data == "profile:change")
async def change_nick_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileFlow.new_nick)
    ref = await edit_branded(call, "Введи новый Minecraft-ник (2–32 символа: латинские буквы, цифры и подчёркивание):",
                             reply_markup=nick_cancel_kb())
    await remember(state, ref)
    await call.answer()

@router.message(ProfileFlow.new_nick)
async def change_nick_enter(message: Message, state: FSMContext):
    nick = (message.text or "").strip()
    if not valid_nick(nick):
        await show(message, state, f"Некорректный ник. {NICK_RULES}\n\nВведи ник ещё раз:", nick_cancel_kb())
        return
    user = await get_user(message.from_user.id)
    if not user:
        await state.clear()
        return
    if nick == user.minecraft_nick:
        await show(message, state, "Это уже твой текущий ник. Введи другой или нажми «Отмена».", nick_cancel_kb())
        return
    async with Session() as s:
        if await nick_taken(s, nick, exclude_telegram_id=message.from_user.id):
            # Остаёмся в состоянии ввода — можно сразу написать другой ник.
            await show(message, state, "Этот ник уже занят (регистр букв не учитывается). Попробуй другой.", nick_cancel_kb())
            return
    await state.update_data(new_nick=nick, old_nick=user.minecraft_nick)
    await state.set_state(ProfileFlow.confirm_nick)
    await show(message, state,
        f"Старый ник: <b>{safe(user.minecraft_nick)}</b>\nНовый ник: <b>{safe(nick)}</b>\n\nПодтвердите смену ника...",
        nick_confirm_kb())

@router.callback_query(F.data == "profile:confirm")
async def change_nick_confirm(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user = await get_user(call.from_user.id)
    if not user or not data.get("new_nick"):
        await state.clear()
        await call.answer("Сессия смены ника истекла.", show_alert=True)
        return
    async with Session() as s:
        # Повторная проверка: пока клиент нажимал «Подтвердить», ник могли занять.
        if await nick_taken(s, data["new_nick"], exclude_telegram_id=call.from_user.id):
            await state.clear()
            await edit_branded(call, "Этот ник уже занят (регистр букв не учитывается). Нажми «Сменить ник» и выбери другой.")
            await call.answer()
            return
        db_user = await s.get(User, user.id)
        db_user.minecraft_nick = data["new_nick"]
        # Защита головы привязана к аккаунту и переезжает на новый ник.
        await sync_head_protection(s, call.from_user.id, data["new_nick"])
        await s.commit()
    await state.clear()
    await edit_branded(call, f"Ник успешно изменён на <b>{safe(data['new_nick'])}</b>.")
    await call.answer("Ник изменён")

@router.callback_query(F.data == "profile:cancel")
async def change_nick_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_branded(call, "Смена ника отменена.")
    await call.answer()
