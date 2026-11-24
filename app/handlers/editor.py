"""Редактор каталога для глав: тот же каталог, что у покупателей, но вместо корзины — «Подтвердить».

Правки копятся в состоянии диалога (FSM) и записываются в базу одной транзакцией только по «Подтвердить»;
«Отменить правки» или любая команда посреди диалога сбрасывают их.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from app.database import Session
from app.models import Product
from app.handlers.admin import IsAdmin
from app.keyboards import ed_cats_kb, ed_products_kb, ed_card_kb, ed_input_back_kb
from app.services.catalog import get_categories
from app.states import EditFlow
from app.utils import safe, price_text
from app.branding import send_branded, edit_branded, ref_of, remember, show

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

NAME_MAX, DESC_MAX, NUM_MAX = 120, 1000, 10_000_000
FIELD_PROMPTS = {
    "name": "Новое название товара (до 120 символов):",
    "price": "Новая цена одной порции в алмазах (целое число, 0 или больше):",
    "portion": "Новое количество штук в одной порции (целое число, 1 или больше):",
    "desc": "Новое описание товара. Отправь «-», чтобы очистить:",
}


# ---------------------------------------------------------------- правки в состоянии диалога

async def get_edits(state: FSMContext) -> dict:
    return (await state.get_data()).get("ed") or {}

def count_changes(edits: dict) -> int:
    return sum(1 for v in edits.values() if v)

def effective(p: Product, e: dict) -> dict:
    """Товар с наложенными (ещё не подтверждёнными) правками."""
    return dict(name=e.get("name", p.name), price=e.get("price", p.price_diamonds),
                portion=e.get("portion", p.portion_size), desc=e.get("desc", p.description or ""),
                hide=bool(e.get("hide")))

async def stage(state: FSMContext, p: Product, field: str, value) -> None:
    """Запоминает правку; если значение совпало с тем, что в базе, правка снимается."""
    edits = await get_edits(state)
    e = dict(edits.get(str(p.id), {}))
    base = dict(name=p.name, price=p.price_diamonds, portion=p.portion_size, desc=p.description or "", hide=False)
    if value == base[field]:
        e.pop(field, None)
    else:
        e[field] = value
    if e:
        edits[str(p.id)] = e
    else:
        edits.pop(str(p.id), None)
    await state.update_data(ed=edits)


# ---------------------------------------------------------------- экраны

async def cats_screen(state: FSMContext, note: str = ""):
    n = count_changes(await get_edits(state))
    text = (f"{note}<b>Редактор каталога</b>\nВыбери категорию, затем товар. Правки применятся только после "
            "«Подтвердить»." + (f"\nНе подтверждено правок: <b>{n}</b>" if n else ""))
    return text, ed_cats_kb(await get_categories(), n)

async def products_screen(state: FSMContext, key: str):
    categories = await get_categories()
    if key not in categories or key == "heads":
        return None
    edits = await get_edits(state)
    async with Session() as s:
        products = (await s.execute(select(Product).where(Product.category == key, Product.is_active.is_(True))
                                    .order_by(Product.sort_order, Product.id))).scalars().all()
    items = []
    for p in products:
        e = edits.get(str(p.id), {})
        v = effective(p, e)
        mark = "🚫 " if v["hide"] else ("✏️ " if e else "")
        items.append((p.id, f"{mark}{v['portion']} шт. · {v['name']} · {price_text(v['price'])}"))
    text = f"<b>{safe(categories[key])}</b>\nВыбери товар для редактирования:" if items else \
           f"<b>{safe(categories[key])}</b>\nВ этой категории пока нет товаров."
    return text, ed_products_kb(items, count_changes(edits))

async def card_screen(state: FSMContext, pid: int):
    edits = await get_edits(state)
    async with Session() as s:
        p = await s.get(Product, pid)
    if not p or not p.is_active:
        return None
    e = edits.get(str(pid), {})
    v = effective(p, e)

    def diff(old, new, fmt=lambda x: x):
        return f"{fmt(old)} → <b>{fmt(new)}</b> ✏️" if old != new else fmt(old)

    categories = await get_categories()
    lines = [f"<b>{safe(v['name'])}</b>",
             f"Категория: {safe(categories.get(p.category, p.category))}",
             f"Название: {diff(safe(p.name), safe(v['name']))}",
             f"Штук в порции: {diff(p.portion_size, v['portion'])}",
             f"Цена за порцию: {diff(p.price_diamonds, v['price'], price_text)}",
             f"Описание: {diff(safe(p.description or '—'), safe(v['desc'] or '—'))}"]
    if v["hide"]:
        lines.append("\n🚫 После подтверждения товар будет скрыт из каталога.")
    lines.append("\nПравки применятся после «Подтвердить».")
    return "\n".join(lines), ed_card_kb(pid, p.category, bool(e), v["hide"], count_changes(edits))


async def open_cats(call: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    text, kb = await cats_screen(state)
    await edit_branded(call, text, reply_markup=kb)
    await call.answer()

async def open_card(call: CallbackQuery, state: FSMContext, pid: int):
    await state.set_state(None)
    screen = await card_screen(state, pid)
    if not screen:
        await call.answer("Товар больше недоступен.", show_alert=True); return
    await edit_branded(call, *screen)
    await call.answer()


# ---------------------------------------------------------------- навигация

@router.callback_query(F.data == "admin:products")
async def ed_open(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(ed={})
    text, kb = await cats_screen(state)
    sent = await send_branded(call.message, text, kb)
    await remember(state, ref_of(sent))
    await call.answer()

@router.callback_query(F.data == "ed:cats")
async def ed_cats(call: CallbackQuery, state: FSMContext):
    await open_cats(call, state)

@router.callback_query(F.data.startswith("ed:cat:"))
async def ed_category(call: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    screen = await products_screen(state, call.data.split(":", 2)[2])
    if not screen:
        await call.answer("Категория не найдена.", show_alert=True); return
    await edit_branded(call, *screen)
    await call.answer()

@router.callback_query(F.data.startswith("ed:p:"))
async def ed_product(call: CallbackQuery, state: FSMContext):
    await open_card(call, state, int(call.data.rsplit(":", 1)[1]))

@router.callback_query(F.data == "ed:cancel")
async def ed_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_branded(call, "Правки отменены, каталог не изменён.")
    await call.answer()


# ---------------------------------------------------------------- ввод значений

@router.callback_query(F.data.startswith("ed:f:"))
async def ed_field(call: CallbackQuery, state: FSMContext):
    _, _, pid, field = call.data.split(":")
    if field not in FIELD_PROMPTS:
        await call.answer(); return
    await state.set_state(EditFlow.value)
    ref = await edit_branded(call, FIELD_PROMPTS[field], reply_markup=ed_input_back_kb(int(pid)))
    await state.update_data(ed_pid=int(pid), ed_field=field, ui_ref=ref)
    await call.answer()

async def name_conflict(state: FSMContext, p: Product, name: str) -> bool:
    """Есть ли в категории другой видимый товар с таким названием (с учётом ещё не подтверждённых правок)."""
    edits = await get_edits(state)
    async with Session() as s:
        others = (await s.execute(select(Product).where(
            Product.category == p.category, Product.is_active.is_(True), Product.id != p.id))).scalars().all()
    for o in others:
        v = effective(o, edits.get(str(o.id), {}))
        if not v["hide"] and v["name"].casefold() == name.casefold():
            return True
    return False

@router.message(EditFlow.value)
async def ed_value(message: Message, state: FSMContext):
    data = await state.get_data()
    pid, field = data.get("ed_pid"), data.get("ed_field")
    async with Session() as s:
        p = await s.get(Product, pid) if pid else None
    if not p or not p.is_active or field not in FIELD_PROMPTS:
        await state.set_state(None)
        text, kb = await cats_screen(state)
        await show(message, state, "Товар больше недоступен.\n\n" + text, kb); return
    raw = (message.text or "").strip()
    back = ed_input_back_kb(pid)
    if field == "name":
        if not 1 <= len(raw) <= NAME_MAX:
            await show(message, state, f"Название должно быть от 1 до {NAME_MAX} символов. Попробуй ещё раз.", back); return
        if await name_conflict(state, p, raw):
            await show(message, state, "В этой категории уже есть товар с таким названием. Введи другое.", back); return
        value = raw
    elif field in ("price", "portion"):
        low = 0 if field == "price" else 1
        if not raw.isdigit() or not low <= int(raw) <= NUM_MAX:
            await show(message, state, f"Нужно целое число от {low} до {NUM_MAX}. Попробуй ещё раз.", back); return
        value = int(raw)
    else:
        if len(raw) > DESC_MAX:
            await show(message, state, f"Описание слишком длинное: максимум {DESC_MAX} символов.", back); return
        value = "" if raw in ("-", "—") else raw
    await stage(state, p, field, value)
    await state.set_state(None)
    screen = await card_screen(state, pid)
    await show(message, state, *screen)


@router.callback_query(F.data.startswith("ed:hide:"))
async def ed_hide(call: CallbackQuery, state: FSMContext):
    pid = int(call.data.rsplit(":", 1)[1])
    async with Session() as s:
        p = await s.get(Product, pid)
    if not p or not p.is_active:
        await call.answer("Товар больше недоступен.", show_alert=True); return
    hidden = bool((await get_edits(state)).get(str(pid), {}).get("hide"))
    await stage(state, p, "hide", not hidden)
    await open_card(call, state, pid)

@router.callback_query(F.data.startswith("ed:reset:"))
async def ed_reset(call: CallbackQuery, state: FSMContext):
    pid = int(call.data.rsplit(":", 1)[1])
    edits = await get_edits(state)
    edits.pop(str(pid), None)
    await state.update_data(ed=edits)
    await open_card(call, state, pid)


# ---------------------------------------------------------------- подтверждение

@router.callback_query(F.data == "ed:ok")
async def ed_confirm(call: CallbackQuery, state: FSMContext):
    edits = {k: v for k, v in (await get_edits(state)).items() if v}
    if not edits:
        await call.answer("Нет правок для применения.", show_alert=True); return
    changed = hidden = skipped = 0
    async with Session() as s, s.begin():
        ids = [int(k) for k in edits]
        products = {p.id: p for p in (await s.execute(select(Product).where(Product.id.in_(ids)))).scalars()}
        categories = {p.category for p in products.values()}
        # Проверяем названия по итогу правок: два видимых товара в категории не должны совпасть.
        final: dict[tuple, list[int]] = {}
        active = (await s.execute(select(Product).where(Product.category.in_(categories), Product.is_active.is_(True)))).scalars().all()
        for p in active:
            v = effective(p, edits.get(str(p.id), {}))
            if not v["hide"]:
                final.setdefault((p.category, v["name"].casefold()), []).append(p.id)
        dup = [ids_ for ids_ in final.values() if len(ids_) > 1]
        if dup:
            names = ", ".join(sorted({safe(effective(products.get(i) or next(a for a in active if a.id == i), edits.get(str(i), {}))["name"])
                                      for ids_ in dup for i in ids_}))
            await call.answer("Названия совпадают: " + names[:150], show_alert=True)
            return
        for pid, e in ((int(k), v) for k, v in edits.items()):
            p = products.get(pid)
            if not p or not p.is_active:
                skipped += 1
                continue
            v = effective(p, e)
            if v["hide"]:
                p.is_active = False
                hidden += 1
            else:
                p.name, p.price_diamonds, p.portion_size = v["name"], v["price"], v["portion"]
                p.description = v["desc"] or None
            changed += 1
    await state.update_data(ed={})
    await state.set_state(None)
    note = f"✅ Применено правок: {changed}" + (f" (скрыто товаров: {hidden})" if hidden else "") + \
           (f". Пропущено (товар уже недоступен): {skipped}" if skipped else "") + "\n\n"
    text, kb = await cats_screen(state, note)
    await edit_branded(call, text, reply_markup=kb)
    await call.answer("Каталог обновлён")
