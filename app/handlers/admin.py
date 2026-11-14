from aiogram import Router, F
from aiogram.filters import Command, BaseFilter
from aiogram.types import LinkPreviewOptions
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func, delete, update
from app.database import Session
from app.models import User, Product, PickupPoint, Order, Sale, CartItem
from app.handlers.common import get_user
from app.keyboards import admin_menu
from app.states import AdminFlow
from app.utils import safe, price_text, NICK_PLACEHOLDER, valid_nick, utcnow
from app.models import Category
from app.services.catalog import export_catalog, apply_catalog, parse_catalog_json, get_categories
from app.middleware import PERMANENT_BAN
from app.config import settings
from app.services.orders import sales_statistics

router = Router()

def is_admin(user): return bool(user and user.role == "admin")

class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        return is_admin(await get_user(event.from_user.id))

# Весь роутер — только для глав (включая шаги диалогов добавления товаров/пунктов).
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

def ci_nick(column, nick: str):
    """Сравнение ника без учёта регистра. ilike тут нельзя: «_» в LIKE — это подстановочный знак."""
    return func.lower(column) == nick.lower()

@router.message(F.text == "Статистика")
async def stats_button(message: Message):
    await send_stats(message)

async def send_stats(target):
    stats = await sales_statistics()
    week_sum, week_count = stats["week"]
    month_sum, month_count = stats["month"]
    all_sum, all_count = stats["all"]
    unpaid_sum, unpaid_count = stats["unpaid"]
    text = ("<b>Статистика NetherShop</b>\n\n"
            f"За 7 дней: <b>{price_text(week_sum)}</b> · заказов: {week_count}\n"
            f"За 30 дней: <b>{price_text(month_sum)}</b> · заказов: {month_count}\n"
            f"За всё время: <b>{price_text(all_sum)}</b> · заказов: {all_count}\n\n"
            f"Ждёт оплаты: <b>{price_text(unpaid_sum)}</b> · заказов: {unpaid_count}\n\n"
            "В продажи попадают только заказы с подтверждённой сотрудником оплатой.")
    if isinstance(target, Message):
        await target.answer(text)
    else:
        await target.message.answer(text)

@router.callback_query(F.data == "admin:stats")
async def stats_callback(call: CallbackQuery):
    await send_stats(call)
    await call.answer()

# «Кастомизииировать» — старое написание кнопки: у тех, кто не нажимал /start, клавиатура ещё со старым текстом.
@router.message(F.text.in_({"Кастомизировать", "Кастомизииировать"}))
async def customize(message: Message):
    await message.answer("Панель главы NetherShop:", reply_markup=admin_menu())

@router.callback_query(F.data == "admin:add_product")
async def add_product_start(call: CallbackQuery, state: FSMContext):
    await state.clear()  # иначе остатки прерванного «изменить описание» превратят шаг в редактирование
    categories = await get_categories()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"admin:pcat:{key}")]
        for key, name in categories.items() if key != "heads"
    ])
    await call.message.answer("Выбери категорию нового товара:", reply_markup=kb)
    await state.set_state(AdminFlow.product_category); await call.answer()

@router.callback_query(F.data.startswith("admin:pcat:"))
async def product_category(call: CallbackQuery, state: FSMContext):
    await state.update_data(product_category=call.data.split(":")[-1])
    await state.set_state(AdminFlow.product_name)
    await call.message.answer("Название товара:")
    await call.answer()

@router.message(AdminFlow.product_name)
async def product_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 120:
        await message.answer("Название должно быть от 1 до 120 символов."); return
    await state.update_data(product_name=name)
    await state.set_state(AdminFlow.product_portion); await message.answer("Количество предметов в одной порции (число):")

@router.message(AdminFlow.product_portion)
async def product_portion(message: Message, state: FSMContext):
    try: n = int(message.text)
    except (TypeError, ValueError, IndexError): await message.answer("Нужно целое число."); return
    if n < 1: await message.answer("Число должно быть больше нуля."); return
    await state.update_data(product_portion=n); await state.set_state(AdminFlow.product_price)
    await message.answer("Цена одной порции в алмазах (целое число):")

@router.message(AdminFlow.product_price)
async def product_price(message: Message, state: FSMContext):
    try: n = int(message.text)
    except (TypeError, ValueError, IndexError): await message.answer("Нужно целое число."); return
    if n < 0: await message.answer("Цена не может быть отрицательной."); return
    await state.update_data(product_price=n); await state.set_state(AdminFlow.product_description)
    await message.answer("Описание/подробности товара (или отправь «-» для пропуска):")

@router.callback_query(F.data == "admin:products")
async def list_products(call: CallbackQuery):
    async with Session() as s:
        q = await s.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.category, Product.sort_order, Product.id)); items = q.scalars().all()
        cq = await s.execute(select(Category).where(Category.is_active.is_(True)))
        category_names = {c.key: c.button for c in cq.scalars().all()}
    if not items: await call.message.answer("Каталог пуст.")
    for p in items:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Изменить цену", callback_data=f"admin:price:{p.id}"),
             InlineKeyboardButton(text="Изменить описание", callback_data=f"admin:description:{p.id}")],
            [InlineKeyboardButton(text="Удалить", callback_data=f"admin:delete_product:{p.id}")]
        ])
        await call.message.answer(f"{safe(category_names.get(p.category,p.category))}: {safe(p.name)}\n{p.portion_size} шт. · {price_text(p.price_diamonds)}\n{safe(p.description or 'Без описания')}", reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("admin:delete_product:"))
async def delete_product(call: CallbackQuery):
    pid = int(call.data.rsplit(":",1)[1])
    async with Session() as s:
        p = await s.get(Product,pid)
        if p: p.is_active = False; await s.commit()
    await call.message.edit_text("Товар скрыт из каталога."); await call.answer()

@router.callback_query(F.data.startswith("admin:price:"))
async def price_start(call: CallbackQuery, state: FSMContext):
    pid = int(call.data.rsplit(":",1)[1]); await state.update_data(edit_product_id=pid)
    await state.set_state(AdminFlow.edit_product_price)
    await call.message.answer("Новая цена в алмазах:")
    await call.answer()

@router.message(AdminFlow.edit_product_price)
async def edit_product_price(message: Message, state: FSMContext):
    try:
        price = int(message.text)
        if price < 0: raise ValueError
    except (TypeError, ValueError):
        await message.answer("Введи целое неотрицательное число.")
        return
    data = await state.get_data()
    async with Session() as s:
        p = await s.get(Product, int(data["edit_product_id"]))
        if p:
            p.price_diamonds = price
            await s.commit()
    await state.clear()
    await message.answer(f"Цена обновлена: {price_text(price)}")

@router.callback_query(F.data.startswith("admin:description:"))
async def description_start(call: CallbackQuery, state: FSMContext):
    pid = int(call.data.rsplit(":", 1)[1])
    await state.update_data(edit_description_product_id=pid)
    await state.set_state(AdminFlow.product_description)
    await call.message.answer("Новое описание товара (отправь «-», чтобы очистить):")
    await call.answer()

@router.message(AdminFlow.product_description)
async def description_save(message: Message, state: FSMContext):
    data = await state.get_data()
    # If this is an edit flow, update existing product; otherwise it is the add-product flow.
    if data.get("edit_description_product_id"):
        description = None if (message.text or "").strip() in ("—", "-") else (message.text or "").strip()
        async with Session() as s:
            p = await s.get(Product, int(data["edit_description_product_id"]))
            if p:
                p.description = description
                await s.commit()
        await state.clear()
        await message.answer("Описание товара обновлено.")
        return
    desc = None if (message.text or "").strip() in ("—", "-") else (message.text or "").strip()
    async with Session() as s:
        same = [p for p in (await s.execute(select(Product).where(Product.category == data["product_category"]))).scalars().all()
                if p.name.casefold() == data["product_name"].casefold()]   # lower() в SQLite не понимает кириллицу
        # Новый (или возвращённый) товар встаёт в самый низ категории.
        bottom = (await s.scalar(select(func.max(Product.sort_order)).where(Product.category == data["product_category"]))) or 0
        if any(p.is_active for p in same):
            await state.clear()
            await message.answer(f"Товар «{safe(data['product_name'])}» в этой категории уже есть. "
                                 "Измени его через «Список товаров».")
            return
        if same:
            # Раньше скрытый товар с таким названием — возвращаем его, а не создаём дубль.
            p = sorted(same, key=lambda x: x.id)[0]
            p.name = data["product_name"]; p.portion_size = data["product_portion"]
            p.price_diamonds = data["product_price"]; p.description = desc; p.is_active = True
            p.sort_order = bottom + 1
        else:
            s.add(Product(category=data["product_category"], name=data["product_name"], portion_size=data["product_portion"],
                          price_diamonds=data["product_price"], description=desc, is_active=True,
                          sort_order=bottom + 1))
        await s.commit()
    await state.clear()
    await message.answer(f"Товар добавлен: {safe(data['product_name'])} — {price_text(data['product_price'])}")

@router.callback_query(F.data == "admin:catalog_file")
async def send_catalog_file(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlow.catalog_upload)
    content = await export_catalog()
    document = BufferedInputFile(content, filename="nethershop_catalog.json")
    await call.message.answer_document(
        document,
        caption=("Текущий каталог в формате JSON. Отредактируй файл и отправь его сюда "
                 "ответным сообщением. Формат: категория → button + items, "
                 "товар: [название, количество, цена].")
    )
    await call.answer()


@router.message(AdminFlow.catalog_upload, F.document)
async def receive_catalog_file(message: Message, state: FSMContext):
    document = message.document
    if document.file_name != "nethershop_catalog.json":
        await message.answer("Отправь файл с исходным названием nethershop_catalog.json.")
        return
    if document.file_size and document.file_size > 2_000_000:
        await message.answer("Файл слишком большой. Максимальный размер — 2 МБ.")
        return
    from io import BytesIO
    buffer = BytesIO()
    await message.bot.download(document, destination=buffer)
    try:
        data = parse_catalog_json(buffer.getvalue())
        products_count, categories_count = await apply_catalog(data)
    except ValueError as exc:
        await message.answer(f"Файл не применён. {safe(str(exc))}")
        return
    except Exception:
        await message.answer("Не удалось обновить каталог из-за внутренней ошибки. База не должна была измениться.")
        raise
    await state.clear()
    await message.answer(
        f"Каталог успешно обновлён. Категорий: {categories_count}, товаров: {products_count}."
    )


@router.message(AdminFlow.catalog_upload)
async def catalog_upload_wrong_content(message: Message):
    await message.answer("Ожидаю JSON-файл. Отправь документ с расширением .json.")


@router.callback_query(F.data == "admin:add_point")
async def add_point_start(call: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(AdminFlow.point_name); await call.message.answer("Название пункта выдачи:"); await call.answer()

@router.message(AdminFlow.point_name)
async def point_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 100:
        await message.answer("Название должно быть от 1 до 100 символов."); return
    await state.update_data(point_name=name); await state.set_state(AdminFlow.point_dimension)
    await message.answer("Измерение (Обычный мир / Незер / Энд):")

@router.message(AdminFlow.point_dimension)
async def point_dimension(message: Message, state: FSMContext):
    dim = (message.text or "").strip()
    if not 1 <= len(dim) <= 32:
        await message.answer("Название измерения — от 1 до 32 символов."); return
    await state.update_data(point_dimension=dim); await state.set_state(AdminFlow.point_x)
    await message.answer("Координата X:")

@router.message(AdminFlow.point_x)
async def point_x(message: Message, state: FSMContext):
    try: v=int(message.text)
    except (TypeError, ValueError, IndexError): await message.answer("Введи целое число."); return
    await state.update_data(point_x=v); await state.set_state(AdminFlow.point_y); await message.answer("Координата Y:")

@router.message(AdminFlow.point_y)
async def point_y(message: Message, state: FSMContext):
    try: v=int(message.text)
    except (TypeError, ValueError, IndexError): await message.answer("Введи целое число."); return
    await state.update_data(point_y=v); await state.set_state(AdminFlow.point_z); await message.answer("Координата Z:")

@router.message(AdminFlow.point_z)
async def point_z(message: Message, state: FSMContext):
    try: v=int(message.text)
    except (TypeError, ValueError, IndexError): await message.answer("Введи целое число."); return
    d=await state.get_data()
    async with Session() as s:
        s.add(PickupPoint(name=d["point_name"],dimension=d["point_dimension"],x=d["point_x"],y=d["point_y"],z=v,is_active=True))
        await s.commit()
    await state.clear(); await message.answer("Пункт выдачи добавлен.")

@router.callback_query(F.data == "admin:points")
async def list_points(call: CallbackQuery):
    async with Session() as s:
        q=await s.execute(select(PickupPoint).where(PickupPoint.is_active.is_(True)).order_by(PickupPoint.name)); points=q.scalars().all()
    if not points: await call.message.answer("Пунктов выдачи пока нет.")
    for p in points:
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Удалить",callback_data=f"admin:delete_point:{p.id}")]])
        await call.message.answer(f"{safe(p.name)} — {safe(p.dimension)} ({p.x}, {p.y}, {p.z})",reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("admin:delete_point:"))
async def delete_point(call: CallbackQuery):
    pid=int(call.data.rsplit(":",1)[1])
    async with Session() as s:
        p=await s.get(PickupPoint,pid)
        if p: p.is_active=False; await s.commit()
    await call.message.edit_text("Пункт выдачи скрыт."); await call.answer()

@router.message(Command("add_worker"))
async def add_worker(message: Message):
    try: tid=int(message.text.split()[1])
    except (TypeError, ValueError, IndexError): await message.answer("Использование: /add_worker &lt;tg_id&gt;"); return
    async with Session() as s:
        q=await s.execute(select(User).where(User.telegram_id==tid)); u=q.scalar_one_or_none()
        if u and u.role == "admin":
            await message.answer("Этот пользователь уже глава. Сначала снимите роль: /delete_admin."); return
        if u: u.role="worker"
        else: s.add(User(telegram_id=tid,minecraft_nick=NICK_PLACEHOLDER,role="worker"))
        await s.commit()
    await message.answer(f"Пользователь {tid} назначен исполнителем.")

@router.message(Command("delete_worker"))
async def delete_worker(message: Message):
    try: tid=int(message.text.split()[1])
    except (TypeError, ValueError, IndexError): await message.answer("Использование: /delete_worker &lt;tg_id&gt;"); return
    async with Session() as s:
        q=await s.execute(select(User).where(User.telegram_id==tid)); u=q.scalar_one_or_none()
        if u and u.role=="worker":
            u.role="client"
            # Незавершённые заказы снятого исполнителя возвращаем в очередь, иначе они зависнут.
            await s.execute(update(Order).where(Order.worker_id==u.id, Order.status=="in_progress").values(status="pending", worker_id=None))
            await s.commit()
    await message.answer("Роль исполнителя снята.")

@router.message(Command("add_admin"))
async def add_admin(message: Message):
    try: tid=int(message.text.split()[1])
    except (TypeError, ValueError, IndexError): await message.answer("Использование: /add_admin &lt;tg_id&gt;"); return
    async with Session() as s:
        q=await s.execute(select(User).where(User.telegram_id==tid)); u=q.scalar_one_or_none()
        if u: u.role="admin"
        else: s.add(User(telegram_id=tid,minecraft_nick=NICK_PLACEHOLDER,role="admin"))
        await s.commit()
    await message.answer(f"Пользователь {tid} назначен главой.")

@router.message(Command("delete_admin"))
async def delete_admin(message: Message):
    try: tid=int(message.text.split()[1])
    except (TypeError, ValueError, IndexError): await message.answer("Использование: /delete_admin &lt;tg_id&gt;"); return
    if tid==settings.admin_id: await message.answer("Нельзя снять роль с главного ADMIN_ID."); return
    async with Session() as s:
        q=await s.execute(select(User).where(User.telegram_id==tid)); u=q.scalar_one_or_none()
        if u and u.role=="admin": u.role="worker"; await s.commit()
    await message.answer("Роль главы снята, пользователь оставлен исполнителем.")


# --- Управление уникальными головами ---
from datetime import datetime, timedelta
from app.models import UnsellableHead


def add_months(value: datetime, months: int) -> datetime:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    import calendar
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)

@router.message(Command("make_unsellable_head", "male_unsellable_head"))
async def make_unsellable_head(message: Message):
    parts = (message.text or "").split()
    if len(parts) not in (2, 3):
        await message.answer("Использование: /make_unsellable_head &lt;nickname&gt; [число_месяцев]. Без числа месяцев — навсегда.")
        return
    nick = parts[1]
    if not valid_nick(nick):
        await message.answer("Некорректный Minecraft-ник."); return
    months = None
    if len(parts) == 3:
        try: months = int(parts[2])
        except ValueError: months = 0
        if months < 1 or months > 1200:
            await message.answer("Число месяцев должно быть от 1 до 1200."); return
    expires = add_months(utcnow(), months) if months else None
    async with Session() as s:
        q = await s.execute(select(UnsellableHead).where(ci_nick(UnsellableHead.nickname, nick)))
        obj = q.scalars().first()
        # Если игрок зарегистрирован — привязываем защиту к его Telegram-аккаунту (переживёт смену ника).
        owner = (await s.execute(select(User).where(ci_nick(User.minecraft_nick, nick)))).scalars().first()
        if obj:
            obj.nickname = owner.minecraft_nick if owner else nick
            obj.expires_at = expires
            if owner: obj.telegram_id = owner.telegram_id
        else:
            s.add(UnsellableHead(nickname=owner.minecraft_nick if owner else nick, expires_at=expires,
                                 telegram_id=owner.telegram_id if owner else None))
        await s.commit()
    await message.answer(f"Голова {safe(nick)} теперь недоступна для заказа: {'навсегда' if months is None else f'на {months} мес.'}.")

@router.message(Command("make_sellable_head"))
async def make_sellable_head(message: Message):
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Использование: /make_sellable_head &lt;nickname&gt;"); return
    async with Session() as s:
        q = await s.execute(select(UnsellableHead).where(ci_nick(UnsellableHead.nickname, parts[1])))
        obj = q.scalars().first()
        if obj:
            await s.delete(obj); await s.commit()
    await message.answer(f"Голова {safe(parts[1])} снова доступна для заказа.")

@router.message(Command("list_unsellable_heads", "list_unsallable_heads"))
async def list_unsellable_heads(message: Message):
    now = utcnow()
    async with Session() as s:
        q = await s.execute(select(UnsellableHead).order_by(UnsellableHead.nickname))
        rows = q.scalars().all()
        # Clean expired subscriptions while listing.
        active = []
        for row in rows:
            if row.expires_at is not None and row.expires_at <= now:
                await s.delete(row)
            else:
                active.append(row)
        await s.commit()
    if not active:
        await message.answer("Список пуст."); return
    lines = []
    for row in active:
        days = "Навсегда" if row.expires_at is None else str(max(0, (row.expires_at - now).days + (1 if (row.expires_at - now).seconds else 0)))
        lines.append(f"{safe(row.nickname)} — {days if days == 'Навсегда' else days + ' дн.'}")
    await message.answer("<b>Головы, недоступные для заказа</b>\n" + "\n".join(lines))

# --- Блокировка игроков ---
@router.message(Command("ban"))
async def ban_player(message: Message):
    parts = (message.text or "").split()
    if len(parts) not in (2, 3):
        await message.answer("Использование: /ban &lt;nickname&gt; [количество_дней]. Без срока — навсегда."); return
    nick = parts[1]
    until = PERMANENT_BAN  # без срока — навсегда (None означает «не забанен»)
    if len(parts) == 3:
        try: days = int(parts[2])
        except ValueError: days = 0
        if days < 1 or days > 36500:
            await message.answer("Количество дней должно быть от 1 до 36500."); return
        until = utcnow() + timedelta(days=days)
    async with Session() as s:
        q = await s.execute(select(User).where(ci_nick(User.minecraft_nick, nick)))
        user = q.scalars().first()
        if not user:
            await message.answer("Игрок с таким ником не найден."); return
        if user.role == "admin":
            await message.answer("Нельзя заблокировать главу."); return
        user.banned_until = until
        await s.commit()
    await message.answer(f"Игрок {safe(nick)} заблокирован {'навсегда' if until == PERMANENT_BAN else f'до {until:%d.%m.%Y %H:%M} UTC'}.")

@router.message(Command("unban"))
async def unban_player(message: Message):
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Использование: /unban &lt;nickname&gt;"); return
    async with Session() as s:
        q = await s.execute(select(User).where(ci_nick(User.minecraft_nick, parts[1])))
        user = q.scalars().first()
        if not user:
            await message.answer("Игрок с таким ником не найден."); return
        user.banned_until = None
        await s.commit()
    await message.answer(f"Игрок {safe(parts[1])} разблокирован.")

@router.message(Command("list"))
async def list_registered_players(message: Message):
    async with Session() as s:
        q = await s.execute(
            select(User.minecraft_nick, User.telegram_id, User.telegram_username,
                   func.coalesce(func.sum(Sale.total_diamonds), 0).label("spent"))
            .outerjoin(Sale, Sale.user_id == User.id)
            .where(User.minecraft_nick != "Не указан")
            .group_by(User.id)
            .order_by(func.coalesce(func.sum(Sale.total_diamonds), 0).desc(), User.minecraft_nick.asc())
        )
        rows = q.all()
    if not rows:
        await message.answer("Зарегистрированных игроков пока нет."); return
    lines = []
    for i, (nick, tid, username, spent) in enumerate(rows, 1):
        contact = (f'<a href="https://t.me/{safe(username)}">@{safe(username)}</a>'
                   if username else f'<a href="tg://user?id={tid}">Открыть профиль</a>')
        lines.append(f"{i}. {safe(nick)} → {contact} → {price_text(int(spent or 0))}")
    chunk = "<b>Игроки NetherShop (по расходам)</b>\n"
    for line in lines:
        if len(chunk) + len(line) + 1 > 3900:
            await message.answer(chunk, link_preview_options=LinkPreviewOptions(is_disabled=True))
            chunk = ""
        chunk += line + "\n"
    if chunk.strip(): await message.answer(chunk, link_preview_options=LinkPreviewOptions(is_disabled=True))


@router.message(Command("delete"))
async def delete_player(message: Message):
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Использование: /delete &lt;nickname&gt;"); return
    nick = parts[1]
    async with Session() as s:
        q = await s.execute(select(User).where(ci_nick(User.minecraft_nick, nick)).order_by(User.id))
        matches = q.scalars().all()
        if not matches:
            await message.answer("Игрок с таким ником не найден."); return
        # Если из-за старых данных нашлось несколько ников, отличающихся регистром, берём точное совпадение.
        exact = [u for u in matches if u.minecraft_nick == nick]
        if len(matches) > 1 and len(exact) != 1:
            await message.answer("Найдено несколько игроков с таким ником (отличаются регистром). Укажи ник точно, с тем же регистром, как в /list.")
            return
        user = exact[0] if len(matches) > 1 else matches[0]
        if user.telegram_id == message.from_user.id:
            await message.answer("Нельзя удалить собственную учётную запись этой командой."); return
        if user.telegram_id == settings.admin_id:
            await message.answer("Нельзя удалить главного администратора (ADMIN_ID)."); return
        # Заказы клиента удаляем; заказы, которые он выполнял как исполнитель, возвращаем в очередь
        # (иначе они зависнут в «В исполнении» без исполнителя); статистику продаж сохраняем.
        await s.execute(delete(Order).where(Order.user_id == user.id))
        await s.execute(delete(CartItem).where(CartItem.telegram_id == user.telegram_id))
        await s.execute(update(Order).where(Order.worker_id == user.id, Order.status == "in_progress")
                        .values(status="pending", worker_id=None))
        await s.execute(update(Order).where(Order.worker_id == user.id).values(worker_id=None))
        await s.execute(update(Sale).where(Sale.user_id == user.id).values(user_id=None))
        shown = user.minecraft_nick
        await s.delete(user)
        await s.commit()
    await message.answer(f"Пользователь <b>{safe(shown)}</b> полностью удалён из базы. При следующем /start ему потребуется зарегистрироваться заново.")
