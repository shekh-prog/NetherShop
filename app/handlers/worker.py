from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from app.database import Session
from app.models import User
from app.handlers.common import get_user
from app.keyboards import worker_orders_kb, order_actions
from app.services.orders import (list_worker_orders, get_order, accept_order, release_order, set_ready,
                                 delete_order, confirm_payment)
from app.states import CancelFlow
from app.utils import STATUS, safe, price_text

router = Router()

async def notify(bot, chat_id, text):
    """Клиент мог заблокировать бота — это не должно ломать действие исполнителя."""
    try:
        await bot.send_message(chat_id, text)
    except Exception:
        pass

@router.message(F.text == "Выполнить заказ")
async def worker_list(message: Message):
    user = await get_user(message.from_user.id)
    if not user or user.role not in ("worker", "admin"): return
    rows = await list_worker_orders(user.id)
    if not rows:
        await message.answer("Заказов пока нет."); return
    objects = []
    for order, nick in rows:
        order.minecraft_nick = nick
        objects.append(order)
    await message.answer("Заказы (свободные, ваши и ожидающие проверки оплаты):", reply_markup=worker_orders_kb(objects))

@router.callback_query(F.data.startswith("worker:order:"))
async def order_detail(call: CallbackQuery):
    order_id = int(call.data.rsplit(":", 1)[1]); row = await get_order(order_id)
    if not row: await call.answer("Заказ не найден.", show_alert=True); return
    order, user, point = row
    worker = await get_user(call.from_user.id)
    if not worker or worker.role not in ("worker", "admin"):
        await call.answer("Недостаточно прав.", show_alert=True); return
    contact = f"@{safe(user.telegram_username)}" if user.telegram_username else f'<a href="tg://user?id={user.telegram_id}">Открыть профиль</a> (ID: {user.telegram_id})'
    text = (f"<b>Заказ #{order.id}</b>\nКлиент: {safe(user.minecraft_nick)}\nКонтакт: {contact}\n"
            f"{safe(order.items_text)}\n\nПункт: {safe(point.name)} — {safe(point.dimension)} ({point.x}, {point.y}, {point.z})\n"
            f"Сумма: {price_text(order.total_diamonds)}\nСтатус: {STATUS.get(order.status, order.status)}")
    await call.message.answer(text, reply_markup=order_actions(order.id, order.status, order.worker_id, worker.id, order.total_diamonds))
    await call.answer()

@router.callback_query(F.data.startswith("worker:accept:"))
async def accept(call: CallbackQuery):
    order_id = int(call.data.rsplit(":", 1)[1]); worker = await get_user(call.from_user.id)
    if not worker or worker.role not in ("worker", "admin"):
        await call.answer("Недостаточно прав.", show_alert=True); return
    ok = await accept_order(order_id, worker.id)
    await call.answer("Заказ принят." if ok else "Заказ уже принял другой исполнитель.", show_alert=True)
    if ok:
        row = await get_order(order_id)
        if row:
            order, user, point = row
            await notify(call.bot, user.telegram_id, f"Заказ #{order_id} принят исполнителем и находится в работе.")
            await call.message.edit_reply_markup(reply_markup=order_actions(order.id, order.status, order.worker_id, worker.id, order.total_diamonds))

@router.callback_query(F.data.startswith("worker:release:"))
async def release(call: CallbackQuery):
    order_id = int(call.data.rsplit(":", 1)[1]); worker = await get_user(call.from_user.id)
    if not worker or worker.role not in ("worker", "admin"):
        await call.answer("Недостаточно прав.", show_alert=True); return
    ok = await release_order(order_id, worker.id)
    await call.answer("Заказ снова доступен исполнителям." if ok else "Не удалось бросить заказ.", show_alert=True)
    if ok:
        row = await get_order(order_id)
        if row:
            order, user, point = row
            await notify(call.bot, user.telegram_id, f"Исполнитель освободил заказ #{order_id}. Он снова ожидает исполнителя.")
        await call.message.edit_reply_markup(reply_markup=None)

@router.callback_query(F.data.startswith("worker:ready:"))
async def ready(call: CallbackQuery):
    order_id = int(call.data.rsplit(":", 1)[1]); worker = await get_user(call.from_user.id)
    if not worker or worker.role not in ("worker", "admin"):
        await call.answer("Недостаточно прав.", show_alert=True); return
    ok = await set_ready(order_id, worker.id)
    await call.answer("Заказ отмечен как прибывший в пункт выдачи." if ok else "Не удалось обновить статус.", show_alert=True)
    if ok:
        row = await get_order(order_id)
        if row:
            order, user, point = row
            text = f"Заказ #{order_id} прибыл в пункт выдачи!\n{safe(point.name)}: {safe(point.dimension)} ({point.x}, {point.y}, {point.z})"
            if order.total_diamonds > 0:
                text += (f"\n\n💎 К оплате: <b>{price_text(order.total_diamonds)}</b>\n"
                         "Оставь эту сумму в одном из сундуков, в котором лежит твой заказ. "
                         "Долг записан в твой профиль.\n"
                         "Когда заберёшь заказ, нажми «Забрал заказ» в разделе «Мои заказы».")
            await notify(call.bot, user.telegram_id, text)
            await call.message.edit_reply_markup(reply_markup=order_actions(order.id, order.status, order.worker_id, worker.id, order.total_diamonds))

@router.callback_query(F.data.startswith("worker:paid:"))
async def paid(call: CallbackQuery):
    worker = await get_user(call.from_user.id)
    if not worker or worker.role not in ("worker", "admin"):
        await call.answer("Недостаточно прав.", show_alert=True); return
    order_id = int(call.data.rsplit(":", 1)[1])
    result = await confirm_payment(order_id)
    if not result:
        await call.answer("Оплата уже подтверждена или заказ недоступен.", show_alert=True)
        try: await call.message.edit_reply_markup(reply_markup=None)
        except Exception: pass
        return
    user_id, total = result
    async with Session() as s:
        client = await s.get(User, user_id)
    if client:
        await notify(call.bot, client.telegram_id,
                     f"Оплата заказа #{order_id} подтверждена: {price_text(total)}. Долг погашен. Спасибо за покупку в NetherShop!")
    try: await call.message.edit_text(f"Оплата по заказу #{order_id} подтверждена: {price_text(total)}. Заказ закрыт.")
    except Exception: pass
    await call.answer("Оплата подтверждена.", show_alert=True)

@router.callback_query(F.data.startswith("worker:cancel:"))
async def cancel_start(call: CallbackQuery, state: FSMContext):
    worker = await get_user(call.from_user.id)
    if not worker or worker.role not in ("worker", "admin"):
        await call.answer("Недостаточно прав.", show_alert=True); return
    order_id = int(call.data.rsplit(":", 1)[1])
    await state.update_data(cancel_order_id=order_id)
    await state.set_state(CancelFlow.reason)
    await call.message.answer("Напиши причину отмены заказа:")
    await call.answer()

@router.message(CancelFlow.reason)
async def cancel_reason(message: Message, state: FSMContext):
    reason = (message.text or "").strip()
    if len(reason) < 3:
        await message.answer("Укажи причину подробнее."); return
    await state.update_data(cancel_reason=reason)
    await state.set_state(CancelFlow.confirm)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await message.answer(f"Подтвердить отмену?\nПричина: {safe(reason)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить отмену", callback_data="worker:cancel_confirm"),
         InlineKeyboardButton(text="Не отменять", callback_data="worker:cancel_abort")]
    ]))

@router.callback_query(F.data == "worker:cancel_abort")
async def cancel_abort(call: CallbackQuery, state: FSMContext):
    await state.clear(); await call.message.edit_text("Отмена заказа не выполнена."); await call.answer()

@router.callback_query(F.data == "worker:cancel_confirm")
async def cancel_confirm(call: CallbackQuery, state: FSMContext):
    data = await state.get_data(); worker = await get_user(call.from_user.id)
    if not worker or worker.role not in ("worker", "admin"):
        await state.clear(); await call.answer("Недостаточно прав.", show_alert=True); return
    payload = await delete_order(int(data["cancel_order_id"]), worker.id)
    if not payload:
        await call.answer("Заказ не найден или уже недоступен.", show_alert=True); await state.clear(); return
    user_id, items_text, total = payload
    async with Session() as s:
        q = await s.execute(select(User).where(User.id == user_id)); user = q.scalar_one_or_none()
    if user:
        await notify(call.bot, user.telegram_id, f"Твой заказ отменён исполнителем.\nПричина: {safe(data['cancel_reason'])}\n\nСостав заказа:\n{safe(items_text)}\nСумма: {price_text(total)}")
    await state.clear()
    await call.message.edit_text("Заказ удалён из базы. Клиент уведомлён.")
    await call.answer()
