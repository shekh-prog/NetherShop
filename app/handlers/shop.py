from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func
from app.database import Session
from app.models import User, Product, PickupPoint, UnsellableHead
from app.services.catalog import get_categories
from app.states import Registration, CartFlow
from app.keyboards import (main_menu, categories_kb, products_kb, item_controls, details_back_kb, cart_kb,
                           pickup_kb, my_order_kb, heads_menu_kb, unique_head_kb, head_back_kb,
                           head_confirm_kb, clear_confirm_kb)
from app.handlers.common import get_user, nick_taken, sync_head_protection
from app.utils import STATUS, MAX_QTY, price_text, safe, valid_nick, NICK_RULES, NICK_PLACEHOLDER, utcnow, DEBT_STATUSES
from app.services.orders import list_user_orders, claim_order, get_order
from app.services import cart as cartsvc
from app.services.cart import cart_total
from app.branding import send_branded, edit_branded, edit_message, ref_of, remember, show

router = Router()

DETAILS_LIMIT = 300

def cart_summary(cart):
    if not cart:
        return "Корзина пуста."
    lines = []
    for i, x in enumerate(cart, 1):
        lines.append(f"{i}. {safe(x['name'])} — {x['portion']} шт. × {x['qty']} порц. = {price_text(x['price']*x['qty'])}")
        if x.get("details"): lines.append(f"   Подробности: {safe(x['details'])}")
        if x.get("head_nick"): lines.append(f"   Ответственность: {'принята' if x.get('head_accept') else 'не принята'}")
        if not x["available"]: lines.append("   ⚠️ Товар больше недоступен — он будет убран при оформлении.")
    return "\n".join(lines) + f"\n\n<b>Итого: {price_text(cart_total(cart))}</b>"

async def total_line(tg_id: int) -> str:
    return f"Текущий итог: {price_text(cart_total(await cartsvc.get_cart(tg_id)))}"

# ---------------------------------------------------------------- регистрация

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    if user and user.minecraft_nick != NICK_PLACEHOLDER:
        async with Session() as s:
            db_user = await s.get(User, user.id)
            if db_user:
                db_user.telegram_username = message.from_user.username
                await s.commit()
        await send_branded(message, f"Добро пожаловать в <b>NetherShop</b>, {safe(user.minecraft_nick)}!", reply_markup=main_menu(user.role))
        return
    await send_branded(message, "Добро пожаловать в <b>NetherShop</b>! Напиши свой Minecraft-ник:")
    await state.set_state(Registration.minecraft_nick)

@router.message(Registration.minecraft_nick)
async def register(message: Message, state: FSMContext):
    nick = (message.text or "").strip()
    if not valid_nick(nick):
        await send_branded(message, f"Некорректный ник. {NICK_RULES}")
        return
    async with Session() as s:
        if await nick_taken(s, nick, exclude_telegram_id=message.from_user.id):
            await send_branded(message, "Этот ник уже занят (регистр букв не учитывается). Попробуй другой.")
            return
        q = await s.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = q.scalar_one_or_none()
        if user:
            user.minecraft_nick = nick
            user.telegram_username = message.from_user.username
        else:
            from app.config import settings
            role = "admin" if message.from_user.id == settings.admin_id else "client"
            user = User(telegram_id=message.from_user.id, minecraft_nick=nick, role=role, telegram_username=message.from_user.username)
            s.add(user)
        await sync_head_protection(s, message.from_user.id, nick)
        await s.commit()
    await state.clear()
    await send_branded(message, f"Ник <b>{safe(nick)}</b> сохранён. Добро пожаловать в NetherShop!", reply_markup=main_menu(user.role))

# ---------------------------------------------------------------- заказы клиента

@router.message(F.text == "Сделать заказ")
async def make_order(message: Message, state: FSMContext):
    # Корзина лежит в БД и не сбрасывается — просто показываем категории.
    await send_branded(message, f"<b>NetherShop</b>\nВыбери категорию. {await total_line(message.from_user.id)}", reply_markup=categories_kb(await get_categories()))

@router.message(F.text == "Мои заказы")
async def my_orders(message: Message):
    user = await get_user(message.from_user.id)
    if not user: return
    rows = await list_user_orders(user.id)
    if not rows:
        await message.answer("У тебя пока нет заказов.")
        return
    for order, point in rows:
        text = (f"<b>Заказ #{order.id}</b>\n{safe(order.items_text)}\n\nПункт выдачи: {safe(point.name)} — {safe(point.dimension)} ({point.x}, {point.y}, {point.z})\n"
                f"Сумма: {price_text(order.total_diamonds)}\nСтатус: <b>{STATUS.get(order.status, order.status)}</b>")
        if order.status in DEBT_STATUSES and order.total_diamonds > 0:
            text += (f"\n\n💎 К оплате: <b>{price_text(order.total_diamonds)}</b> — оставь в одном из сундуков, "
                     "в котором лежит заказ.")
        # Кнопка «Забрал заказ» имеет смысл только пока заказ ждёт клиента в пункте выдачи.
        await message.answer(text, reply_markup=my_order_kb(order.id) if order.status == "ready" else None)

@router.callback_query(F.data.startswith("order:claimed:"))
async def order_claimed(call: CallbackQuery):
    user = await get_user(call.from_user.id)
    if not user:
        await call.answer("Пользователь не найден.", show_alert=True); return
    order_id = int(call.data.rsplit(":", 1)[1])
    result = await claim_order(order_id, user.id)
    if result is None:
        await call.answer("Забрать можно только заказ, прибывший в пункт выдачи.", show_alert=True); return
    if result == "done":
        # Заказ без суммы (только головы): оплаты в сундуке нет, закрываем сразу.
        await edit_branded(call, f"Заказ #{order_id} отмечен как забранный и удалён из списка заказов. Спасибо за покупку в NetherShop!")
        await call.answer("Заказ завершён.", show_alert=True)
        return
    row = await get_order(order_id)
    total = row[0].total_diamonds if row else 0
    await edit_branded(call, f"Заказ #{order_id} отмечен как забранный.\n\n"
                             f"💎 К оплате: <b>{price_text(total)}</b>. Если ещё не оставил оплату — оставь её в одном из сундуков, "
                             "в котором лежал заказ. Сотрудник проверит оплату и закроет заказ; до этого он остаётся "
                             "в списке со статусом «Проверка оплаты», а долг — в твоём профиле.")
    await call.answer("Заказ ждёт проверки оплаты.", show_alert=True)
    if row and row[0].worker_id:
        # Сообщаем исполнителю, который доставил заказ; подтвердить оплату при этом может любой сотрудник.
        async with Session() as s:
            courier = await s.get(User, row[0].worker_id)
        if courier:
            try:
                await call.bot.send_message(courier.telegram_id,
                    f"Клиент {safe(user.minecraft_nick)} забрал заказ #{order_id}. "
                    f"Проверьте оплату ({price_text(total)}) в «Выполнить заказ».")
            except Exception:
                pass

# ---------------------------------------------------------------- каталог

@router.callback_query(F.data.in_({"shop:categories", "shop:back"}))
async def show_categories(call: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await edit_branded(call, f"<b>NetherShop</b>\nВыбери категорию. {await total_line(call.from_user.id)}", reply_markup=categories_kb(await get_categories()))
    await call.answer()

@router.callback_query(F.data.startswith("cat:"))
async def show_products(call: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    category = call.data.split(":", 1)[1]
    if category == "heads":
        await edit_branded(call, "Раздел голов. Выбери действие:", reply_markup=heads_menu_kb())
        await call.answer()
        return
    categories = await get_categories()
    if category not in categories or category == "heads":
        await call.answer("Категория не найдена.", show_alert=True); return
    async with Session() as s:
        q = await s.execute(select(Product).where(Product.category == category, Product.is_active.is_(True)).order_by(Product.sort_order, Product.id))
        products = q.scalars().all()
    if not products:
        await edit_branded(call, "В этой категории пока нет товаров.", reply_markup=categories_kb(await get_categories()))
    else:
        await edit_branded(call, f"<b>{safe(categories[category])}</b>\nВыбери товар:", reply_markup=products_kb(products))
    await call.answer()

async def render_card(tg_id: int, product_id: int, qty: int | None, pending_details: str = ""):
    """Карточка товара. Если товар уже в корзине — открывается с сохранённым количеством."""
    async with Session() as s:
        p = await s.get(Product, product_id)
    if not p or not p.is_active:
        return None
    cur, cur_details = await cartsvc.get_line(tg_id, product_id)
    in_cart = cur > 0
    if qty is None:
        qty = cur if in_cart else 1
    qty = max(0 if in_cart else 1, min(MAX_QTY, qty))
    details = pending_details or cur_details
    text = (f"<b>{safe(p.name)}</b>\nПорция: {p.portion_size} шт.\nЦена за порцию: {price_text(p.price_diamonds)}\n"
            f"Количество порций: <b>{qty}</b>\nИтого за товар: {price_text(p.price_diamonds * qty)}")
    if in_cart:
        text += f"\nСейчас в корзине: {cur} порц."
    if details:
        text += f"\nПодробности: {safe(details)}"
    if p.description:
        text += f"\n\n{safe(p.description)}"
    text += f"\n\n{await total_line(tg_id)}"
    return text, item_controls(p.id, p.category, qty, in_cart, bool(details)), qty

def pending_for(data: dict, pid: int) -> str:
    return data.get("pending_details", "") if data.get("pending_details_pid") == pid else ""

async def open_card(call: CallbackQuery, state: FSMContext, pid: int, qty: int | None):
    await state.set_state(None)
    data = await state.get_data()
    card = await render_card(call.from_user.id, pid, qty, pending_for(data, pid))
    if not card:
        await call.answer("Товар больше недоступен.", show_alert=True); return
    text, kb, _ = card
    await edit_branded(call, text, reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("product:"))
async def product_detail(call: CallbackQuery, state: FSMContext):
    await open_card(call, state, int(call.data.split(":")[1]), None)

@router.callback_query(F.data.startswith("q:"))
async def change_qty(call: CallbackQuery, state: FSMContext):
    _, pid, qty = call.data.split(":")
    await open_card(call, state, int(pid), int(qty))

@router.callback_query(F.data.startswith("qty:"))
async def change_qty_legacy(call: CallbackQuery, state: FSMContext):
    # Кнопки из сообщений старой версии: qty:<pid>:<±1>.
    _, pid, delta = call.data.split(":")
    cur, _ = await cartsvc.get_line(call.from_user.id, int(pid))
    await open_card(call, state, int(pid), max(0, (cur or 1) + int(delta)))

@router.callback_query(F.data.startswith("add:"))
async def add_product(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    pid = int(parts[1]); qty = int(parts[2]) if len(parts) > 2 else 1
    async with Session() as s:
        p = await s.get(Product, pid)
    if not p or not p.is_active:
        await call.answer("Товар больше недоступен.", show_alert=True); return
    data = await state.get_data()
    details = pending_for(data, pid) or None
    if details is not None:
        await state.update_data(pending_details_pid=None, pending_details="")
    # Количество УСТАНАВЛИВАЕТСЯ (а не прибавляется): позиции не дублируются, а лишнее можно убрать.
    await cartsvc.set_qty(call.from_user.id, pid, qty, details)
    if qty <= 0:
        head = f"Убрано из корзины: {safe(p.name)}"
    else:
        head = f"В корзине: {safe(p.name)} × {min(qty, MAX_QTY)} порц."
    await edit_branded(call, f"{head}\n{await total_line(call.from_user.id)}", reply_markup=categories_kb(await get_categories()))
    await call.answer("Корзина обновлена")

# ---------------------------------------------------------------- подробности к товару

@router.callback_query(F.data.startswith("details:"))
async def details_start(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    pid = int(parts[1]); qty = int(parts[2]) if len(parts) > 2 else 1
    await state.set_state(CartFlow.details)
    ref = await edit_branded(call, "Напиши подробности к этой позиции одним сообщением "
                                   "(или отправь «-», чтобы очистить):", reply_markup=details_back_kb(pid, qty))
    await state.update_data(details_product_id=pid, details_qty=qty, ui_ref=ref)
    await call.answer()

@router.message(CartFlow.details)
async def details_save(message: Message, state: FSMContext):
    data = await state.get_data()
    pid = data.get("details_product_id")
    detail = (message.text or "").strip()
    if len(detail) > DETAILS_LIMIT:
        await message.answer(f"Слишком длинно: максимум {DETAILS_LIMIT} символов. Сократи и отправь ещё раз.")
        return
    if detail in ("-", "—"): detail = ""
    if not await cartsvc.set_details(message.from_user.id, pid, detail):
        # Товара ещё нет в корзине — запомним и применим при добавлении.
        await state.update_data(pending_details_pid=pid, pending_details=detail)
    await state.set_state(None)
    fresh = await state.get_data()
    card = await render_card(message.from_user.id, pid, data.get("details_qty"), pending_for(fresh, pid))
    if not card:
        await show(message, state, "Товар больше недоступен.", categories_kb(await get_categories())); return
    text, kb, _ = card
    await show(message, state, text, kb)

# ---------------------------------------------------------------- головы

@router.callback_query(F.data == "heads:buy")
async def heads_buy(call: CallbackQuery, state: FSMContext):
    await state.set_state(CartFlow.head_nick)
    ref = await edit_branded(call, "Введи Minecraft-ник игрока, чью голову хочешь заказать:", reply_markup=head_back_kb())
    await remember(state, ref)
    await call.answer()

@router.callback_query(F.data == "head:cancel")
async def head_cancel(call: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await state.update_data(head_nick=None)
    await edit_branded(call, "Раздел голов. Выбери действие:", reply_markup=heads_menu_kb())
    await call.answer()

@router.callback_query(F.data == "heads:unique")
async def heads_unique(call: CallbackQuery):
    await edit_branded(call,
        "Хотите, чтобы вашу голову нельзя было купить у нас? Без проблем! За 32 алмазных блока в месяц вы можете сделать так, чтобы вашу голову нельзя было заказать в нашем магазине.",
        reply_markup=unique_head_kb())
    await call.answer()

@router.callback_query(F.data == "heads:apply")
async def heads_apply(call: CallbackQuery):
    user = await get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала зарегистрируйся через /start.", show_alert=True)
        return
    async with Session() as s:
        q = await s.execute(select(User).where(User.role == "admin"))
        admins = q.scalars().all()
    contact = f"@{safe(user.telegram_username)}" if user.telegram_username else f'<a href="tg://user?id={user.telegram_id}">Открыть Telegram-профиль</a>'
    notice = ("<b>Заявка на уникальную голову</b>\n"
              f"Игрок: <b>{safe(user.minecraft_nick)}</b>\nTelegram: {contact} (ID: <code>{user.telegram_id}</code>)\n"
              "Условия: 32 алмазных блока за месяц. Свяжитесь с игроком для оплаты и подтверждения.")
    sent = 0
    for admin in admins:
        try:
            await call.bot.send_message(admin.telegram_id, notice)
            sent += 1
        except Exception:
            pass
    await edit_branded(call, "Заявка отправлена главам. Они свяжутся с тобой для обсуждения оплаты.")
    await call.answer("Заявка отправлена" if sent else "Не удалось доставить заявку главам", show_alert=not bool(sent))

@router.message(CartFlow.head_nick)
async def head_nick(message: Message, state: FSMContext):
    nick = (message.text or "").strip()
    if not valid_nick(nick):
        await show(message, state, f"Некорректный ник. {NICK_RULES}\n\nВведи ник ещё раз или нажми «Назад».", head_back_kb())
        return
    async with Session() as s:
        q = await s.execute(select(UnsellableHead).where(func.lower(UnsellableHead.nickname) == nick.lower()))
        protected = q.scalars().first()
        if protected and protected.expires_at is not None and protected.expires_at <= utcnow():
            await s.delete(protected)
            await s.commit()
            protected = None
    if protected:
        # Остаёмся в том же шаге: можно сразу ввести другой ник или вернуться кнопкой.
        await show(message, state,
                   f"Голова игрока <b>{safe(nick)}</b> не продаётся. Повторите попытку — введите другой ник "
                   "или нажмите «Назад».", head_back_kb())
        return
    await state.update_data(head_nick=nick)
    await state.set_state(CartFlow.head_confirm)
    await show(message, state,
        f"Голова игрока <b>{safe(nick)}</b>. Если готовой головы не окажется в наличии, исполнителю придётся её добыть. "
        "В случае жалобы ответственность будет нести заказчик.\n\nПодтверди условия. "
        "Если нажать «Отменить», голова всё равно добавится в корзину, но с пометкой, что ты не принимаешь ответственность.",
        head_confirm_kb())

async def finish_head(call: CallbackQuery, state: FSMContext, accepted: bool):
    nick = (await state.get_data()).get("head_nick")
    if not nick:
        await call.answer("Сессия истекла. Начни заново.", show_alert=True); return
    await cartsvc.add_head(call.from_user.id, nick, accepted)
    await state.update_data(head_nick=None)
    await state.set_state(None)
    await edit_branded(call,
        f"Голова <b>{safe(nick)}</b> добавлена в корзину.\n{await total_line(call.from_user.id)}",
        reply_markup=categories_kb(await get_categories()))
    await call.answer("Добавлено")

@router.callback_query(F.data == "head:confirm")
async def head_confirm(call: CallbackQuery, state: FSMContext):
    await finish_head(call, state, True)

@router.callback_query(F.data == "head:decline")
async def head_decline(call: CallbackQuery, state: FSMContext):
    await finish_head(call, state, False)

# ---------------------------------------------------------------- корзина

async def show_cart(call: CallbackQuery):
    cart = await cartsvc.get_cart(call.from_user.id)
    await edit_branded(call, cart_summary(cart), reply_markup=cart_kb(cart))

@router.callback_query(F.data == "cart:view")
async def view_cart(call: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await show_cart(call)
    await call.answer()

@router.callback_query(F.data.startswith("cart:rm:"))
async def remove_cart_item(call: CallbackQuery):
    await cartsvc.remove_item(call.from_user.id, int(call.data.rsplit(":", 1)[1]))
    await show_cart(call)
    await call.answer("Позиция удалена")

@router.callback_query(F.data == "cart:clear")
async def clear_ask(call: CallbackQuery):
    if not await cartsvc.get_cart(call.from_user.id):
        await call.answer("Корзина уже пуста.", show_alert=True); return
    await edit_branded(call, "Очистить корзину полностью? Все позиции будут убраны.", reply_markup=clear_confirm_kb())
    await call.answer()

@router.callback_query(F.data == "cart:clear_yes")
async def clear_yes(call: CallbackQuery):
    await cartsvc.clear_cart(call.from_user.id)
    await show_cart(call)
    await call.answer("Корзина очищена")

@router.callback_query(F.data == "cart:checkout")
async def checkout(call: CallbackQuery):
    removed = await cartsvc.purge_unavailable(call.from_user.id)
    cart = await cartsvc.get_cart(call.from_user.id)
    if not cart:
        await call.answer("Корзина пуста" if not removed else "Все товары в корзине стали недоступны.", show_alert=True)
        await show_cart(call)
        return
    async with Session() as s:
        q = await s.execute(select(PickupPoint).where(PickupPoint.is_active.is_(True)).order_by(PickupPoint.name))
        points = q.scalars().all()
    if not points:
        await call.answer("Пункты выдачи пока не настроены.", show_alert=True); return
    note = "\n⚠️ Недоступные товары убраны из корзины." if removed else ""
    await edit_branded(call, f"Итого: <b>{price_text(cart_total(cart))}</b>{note}\nВыбери пункт выдачи:", reply_markup=pickup_kb(points))
    await call.answer()

@router.callback_query(F.data.startswith("pickup:"))
async def choose_pickup(call: CallbackQuery):
    point_id = int(call.data.split(":")[1])
    user = await get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала зарегистрируйся через /start.", show_alert=True); return
    async with Session() as s:
        point = await s.get(PickupPoint, point_id)
        if not point or not point.is_active:
            await call.answer("Этот пункт выдачи больше недоступен.", show_alert=True); return
        db_user = await s.get(User, user.id)
        if db_user:
            db_user.telegram_username = call.from_user.username
            await s.commit()
    result = await cartsvc.checkout(call.from_user.id, user.id, point_id)
    if result[0] == "empty":
        await call.answer("Корзина пуста.", show_alert=True); return
    if result[0] == "stale":
        await call.answer("Корзина изменилась. Проверь её и оформи заказ ещё раз.", show_alert=True)
        await show_cart(call); return
    if result[0] == "changed":
        await call.answer("Часть товаров стала недоступна и убрана из корзины. Проверь корзину.", show_alert=True)
        await show_cart(call); return
    _, order_id, total, items_text = result
    await edit_branded(call, f"Заказ <b>#{order_id}</b> отправлен исполнителям!\nСумма: {price_text(total)}")
    async with Session() as s:
        q = await s.execute(select(User).where(User.role.in_(["worker", "admin"])))
        workers = q.scalars().all()
    for worker in workers:
        username_line = f"Контакт: @{safe(call.from_user.username)}" if call.from_user.username else f'<a href="tg://user?id={user.telegram_id}">Открыть профиль заказчика</a> (Telegram ID: {user.telegram_id})'
        try: await call.bot.send_message(worker.telegram_id, f"Новый заказ #{order_id} от {safe(user.minecraft_nick)}\n{username_line}\n{safe(items_text)}\nСумма: {price_text(total)}")
        except Exception: pass
    await call.answer()
