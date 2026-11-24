"""Промокоды: меню для всех, ввод кода, «Мои промокоды»; для глав — создание, список и удаление."""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from app.database import Session
from app.models import Product
from app.handlers.admin import IsAdmin
from app.handlers.common import get_user
from app.keyboards import (promo_menu_kb, back_kb, my_promos_kb, my_promo_view_kb, promo_cats_kb, promo_products_kb,
                           promo_product_confirm_kb, promo_cancel_kb, promo_list_kb, promo_view_kb,
                           promo_delete_confirm_kb)
from app.services import promo as promosvc
from app.services.catalog import get_categories
from app.states import PromoFlow
from app.utils import safe, price_text
from app.branding import send_branded, edit_branded, remember, show

log = logging.getLogger("nethershop")
router = Router()          # доступно всем
admin_router = Router()    # только главы
admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())

MAX_USES = 1_000_000


# ---------------------------------------------------------------- меню (все)

async def menu_text(user) -> str:
    try:
        active = await promosvc.get_active_promo(user.id)
        if active:
            status = (f"Активен: <b>{safe(promosvc.promo_title(active))}</b> — скидка {active['percent']}% "
                      f"{await promosvc.scope_text(active)}. Применится к следующему заказу.")
        else:
            status = "Сейчас нет активного промокода."
    except Exception:
        # Меню должно открываться при любых проблемах с описанием: управление промокодами — внутри него.
        log.exception("Не удалось собрать статус активного промокода")
        status = "Подробности активного промокода смотри в «Мои промокоды»."
    return f"<b>Промокоды</b>\n{status}"


@router.message(F.text == "Промокод")
async def promo_button(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        return
    await send_branded(message, await menu_text(user), reply_markup=promo_menu_kb(user.role == "admin"))


@router.callback_query(F.data == "promo:menu")
async def promo_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(call.from_user.id)
    if not user:
        await call.answer(); return
    await edit_branded(call, await menu_text(user), reply_markup=promo_menu_kb(user.role == "admin"))
    await call.answer()


@router.callback_query(F.data == "promo:enter")
async def promo_enter(call: CallbackQuery, state: FSMContext):
    await state.set_state(PromoFlow.enter_code)
    ref = await edit_branded(call, "Введи промокод одним сообщением:", reply_markup=back_kb("promo:menu"))
    await remember(state, ref)
    await call.answer()


@router.message(PromoFlow.enter_code)
async def promo_entered(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if not user:
        return
    result, promo = await promosvc.redeem(user.id, message.text or "")
    if result == "ok":
        await state.set_state(None)
        await show(message, state,
                   f"✅ Промокод <b>{safe(promosvc.promo_title(promo))}</b> активирован: скидка {promo.percent}% "
                   f"{await promosvc.scope_text(promo)}.\nОна применится к твоему следующему заказу.",
                   back_kb("promo:menu"))
    elif result == "has_active":
        await state.set_state(None)
        await show(message, state,
                   "У тебя уже активен другой промокод, а промокоды не суммируются. Деактивируй текущий в разделе "
                   "«Мои промокоды» и введи этот код снова.", back_kb("promo:menu"))
    elif result == "already":
        await show(message, state, "Ты уже вводил этот промокод: каждый игрок может использовать его только один раз. "
                                   "Введи другой промокод или нажми «Назад».", back_kb("promo:menu"))
    elif result == "exhausted":
        await show(message, state, "Этот промокод уже закончился: лимит использований исчерпан. "
                                   "Введи другой промокод или нажми «Назад».", back_kb("promo:menu"))
    else:
        await show(message, state, "Такого промокода нет. Проверь написание и отправь ещё раз или нажми «Назад».",
                   back_kb("promo:menu"))


# ---------------------------------------------------------------- «Мои промокоды»

def my_promo_text(item: dict, scope: str) -> str:
    if item["used_order_id"] is not None:
        status = f"🔴 Использован в заказе #{item['used_order_id']}"
    elif item["is_active"]:
        status = "🟢 Активен — применится к следующему заказу"
    else:
        status = "🔴 Выключен — не применяется, пока не активируешь"
    return (f"<b>{safe(item['name'] or item['code'])}</b>\nКод: <code>{safe(item['code'])}</code>\n"
            f"Скидка: {item['percent']}% {scope}\nСтатус: {status}")


async def show_my_list(call: CallbackQuery):
    user = await get_user(call.from_user.id)
    items = await promosvc.list_user_promos(user.id) if user else []
    if not items:
        await edit_branded(call, "Ты ещё не вводил промокоды.", reply_markup=back_kb("promo:menu"))
    else:
        await edit_branded(call, "<b>Мои промокоды</b>\n🟢 — активен сейчас, 🔴 — выключен или уже использован.\n"
                                 "Одновременно может быть активен только один.", reply_markup=my_promos_kb(items))


@router.callback_query(F.data == "promo:mine")
async def promo_mine(call: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await show_my_list(call)
    await call.answer()


async def render_my_promo(call: CallbackQuery, rid: int):
    user = await get_user(call.from_user.id)
    item = await promosvc.get_user_promo(rid, user.id) if user else None
    if not item:
        await call.answer("Промокод не найден (возможно, его удалили).", show_alert=True)
        await show_my_list(call)
        return False
    await edit_branded(call, my_promo_text(item, await promosvc.scope_text(item)), reply_markup=my_promo_view_kb(item))
    return True


@router.callback_query(F.data.startswith("promo:my:"))
async def promo_my_view(call: CallbackQuery):
    if await render_my_promo(call, int(call.data.rsplit(":", 1)[1])):
        await call.answer()


@router.callback_query(F.data.startswith("promo:tg:"))
async def promo_toggle(call: CallbackQuery):
    _, _, rid, flag = call.data.split(":")
    user = await get_user(call.from_user.id)
    if not user:
        await call.answer(); return
    result = await promosvc.set_active(int(rid), user.id, flag == "1")
    if result == "conflict":
        await call.answer("Сначала деактивируй другой активный промокод: промокоды не суммируются.", show_alert=True)
        return
    if result == "used":
        await call.answer("Этот промокод уже использован.", show_alert=True)
    elif result == "missing":
        await call.answer("Промокод не найден (возможно, его удалили).", show_alert=True)
        await show_my_list(call)
        return
    else:
        await call.answer("Промокод включён." if flag == "1" else "Промокод выключен.")
    await render_my_promo(call, int(rid))


# ---------------------------------------------------------------- создание (главы)

@admin_router.callback_query(F.data.in_({"promo:new", "pn:new"}))
async def pn_start(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_branded(call, "<b>Создание промокода</b>\nВыбери, на что будет действовать скидка:",
                       reply_markup=promo_cats_kb(await get_categories()))
    await call.answer()


@admin_router.callback_query(F.data == "pn:cancel")
async def pn_cancel(call: CallbackQuery, state: FSMContext):
    await promo_menu(call, state)


async def ask_percent(call: CallbackQuery, state: FSMContext, scope: str, category=None, product_id=None):
    await state.update_data(pn_scope=scope, pn_category=category, pn_product=product_id)
    await state.set_state(PromoFlow.percent)
    where = await promosvc.scope_text(dict(scope=scope, category=category, product_id=product_id))
    ref = await edit_branded(call, f"Промокод будет действовать {where}.\n\n"
                                   "На сколько процентов сделать скидку? Напиши число от 1 до 100 "
                                   "(минус столько-то процентов).", reply_markup=promo_cancel_kb())
    await remember(state, ref)
    await call.answer()


@admin_router.callback_query(F.data == "pn:all")
async def pn_all(call: CallbackQuery, state: FSMContext):
    await ask_percent(call, state, "all")


@admin_router.callback_query(F.data.startswith("pn:allcat:"))
async def pn_all_category(call: CallbackQuery, state: FSMContext):
    await ask_percent(call, state, "category", category=call.data.split(":", 2)[2])


@admin_router.callback_query(F.data.startswith("pn:cat:"))
async def pn_category(call: CallbackQuery):
    key = call.data.split(":", 2)[2]
    categories = await get_categories()
    if key not in categories or key == "heads":
        await call.answer("Категория не найдена.", show_alert=True); return
    async with Session() as s:
        products = (await s.execute(select(Product).where(Product.category == key, Product.is_active.is_(True))
                                    .order_by(Product.sort_order, Product.id))).scalars().all()
    await edit_branded(call, f"<b>{safe(categories[key])}</b>\nВыбери товар или нажми «На всё» — "
                             "тогда скидка будет на всю категорию:", reply_markup=promo_products_kb(products, key))
    await call.answer()


@admin_router.callback_query(F.data.startswith("pn:prod:"))
async def pn_product(call: CallbackQuery):
    async with Session() as s:
        p = await s.get(Product, int(call.data.rsplit(":", 1)[1]))
    if not p or not p.is_active:
        await call.answer("Товар больше недоступен.", show_alert=True); return
    await edit_branded(call, f"<b>{safe(p.name)}</b>\nПорция: {p.portion_size} шт.\nЦена за порцию: {price_text(p.price_diamonds)}\n\n"
                             "Скидка будет действовать только на этот товар.",
                       reply_markup=promo_product_confirm_kb(p.id, p.category))
    await call.answer()


@admin_router.callback_query(F.data.startswith("pn:ok:"))
async def pn_product_ok(call: CallbackQuery, state: FSMContext):
    async with Session() as s:
        p = await s.get(Product, int(call.data.rsplit(":", 1)[1]))
    if not p or not p.is_active:
        await call.answer("Товар больше недоступен.", show_alert=True); return
    await ask_percent(call, state, "product", product_id=p.id)


@admin_router.message(PromoFlow.percent)
async def pn_percent(message: Message, state: FSMContext):
    raw = (message.text or "").strip().rstrip("%").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 100:
        await show(message, state, "Нужно целое число от 1 до 100. Напиши, на сколько процентов сделать скидку.",
                   promo_cancel_kb())
        return
    await state.update_data(pn_percent=int(raw))
    await state.set_state(PromoFlow.name)
    await show(message, state, "Как назвать промокод? Название видно в списке промокодов.\n"
                               "Отправь «-», чтобы пропустить (тогда на кнопке будет сам код).", promo_cancel_kb())


@admin_router.message(PromoFlow.name)
async def pn_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if name in ("-", "—"):
        name = None
    elif not 1 <= len(name) <= 60:
        await show(message, state, "Название — от 1 до 60 символов (или «-», чтобы пропустить).", promo_cancel_kb())
        return
    await state.update_data(pn_name=name)
    await state.set_state(PromoFlow.code)
    await show(message, state, "Придумай уникальный код: латинские буквы, цифры, «_» и «-», от 3 до 32 символов "
                               "(регистр не важен).\nОтправь «-», чтобы бот сгенерировал случайный код из 12 символов.",
               promo_cancel_kb())


@admin_router.message(PromoFlow.code)
async def pn_code(message: Message, state: FSMContext):
    code = (message.text or "").strip()
    if code in ("-", "—"):
        code = None
    elif not promosvc.CODE_RE.fullmatch(code):
        await show(message, state, "Код может состоять из латинских букв, цифр, «_» и «-», длина от 3 до 32. "
                                   "Попробуй ещё раз или отправь «-» для случайного кода.", promo_cancel_kb())
        return
    elif await promosvc.code_exists(code):
        await show(message, state, "Такой код уже есть. Придумай другой или отправь «-» для случайного.", promo_cancel_kb())
        return
    await state.update_data(pn_code=code.upper() if code else None)
    await state.set_state(PromoFlow.uses)
    await show(message, state, "Сколько раз промокод можно использовать в сумме всеми игроками? Напиши число "
                               "(1 — его сможет ввести только один игрок). Каждый игрок в любом случае может ввести "
                               "один и тот же промокод только раз.", promo_cancel_kb())


@admin_router.message(PromoFlow.uses)
async def pn_uses(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= MAX_USES:
        await show(message, state, f"Нужно целое число от 1 до {MAX_USES}.", promo_cancel_kb())
        return
    data = await state.get_data()
    promo = await promosvc.create_promo(data["pn_scope"], data.get("pn_category"), data.get("pn_product"),
                                        data["pn_percent"], data.get("pn_name"), data.get("pn_code"), int(raw))
    if promo is None:
        await state.set_state(PromoFlow.code)
        await show(message, state, "Не удалось создать промокод: такой код уже занят. Придумай другой "
                                   "или отправь «-» для случайного.", promo_cancel_kb())
        return
    await state.set_state(None)
    await show(message, state,
               f"✅ <b>Промокод создан</b>\nНазвание: {safe(promo.name or '—')}\nКод: <code>{safe(promo.code)}</code>\n"
               f"Скидка: {promo.percent}% {await promosvc.scope_text(promo)}\nЛимит использований: {promo.max_uses}",
               back_kb("promo:list"))


# ---------------------------------------------------------------- список (главы)

def promo_info(promo, scope: str) -> str:
    return (f"<b>{safe(promo.name or promo.code)}</b>\nКод: <code>{safe(promo.code)}</code>\n"
            f"Скидка: {promo.percent}% {scope}\nИспользовано: {promo.uses} из {promo.max_uses}\n"
            f"Создан: {promo.created_at:%d.%m.%Y %H:%M} UTC")


@admin_router.callback_query(F.data == "promo:list")
async def promo_list(call: CallbackQuery, state: FSMContext):
    await state.clear()
    promos = await promosvc.list_promos()
    if not promos:
        await edit_branded(call, "Промокодов пока нет.", reply_markup=back_kb("promo:menu"))
    else:
        await edit_branded(call, "<b>Список промокодов</b>\nВыбери промокод, чтобы увидеть подробности и код:",
                           reply_markup=promo_list_kb(promos))
    await call.answer()


@admin_router.callback_query(F.data.startswith("promo:view:"))
async def promo_view(call: CallbackQuery):
    promo = await promosvc.get_promo(int(call.data.rsplit(":", 1)[1]))
    if not promo:
        await call.answer("Промокод не найден.", show_alert=True); return
    await edit_branded(call, promo_info(promo, await promosvc.scope_text(promo)), reply_markup=promo_view_kb(promo.id))
    await call.answer()


@admin_router.callback_query(F.data.startswith("promo:del:"))
async def promo_delete_ask(call: CallbackQuery):
    promo = await promosvc.get_promo(int(call.data.rsplit(":", 1)[1]))
    if not promo:
        await call.answer("Промокод не найден.", show_alert=True); return
    await edit_branded(call, f"Удалить промокод <b>{safe(promo.name or promo.code)}</b> из базы? "
                             "Он пропадёт и у игроков, которые его уже ввели.",
                       reply_markup=promo_delete_confirm_kb(promo.id))
    await call.answer()


@admin_router.callback_query(F.data.startswith("promo:delyes:"))
async def promo_delete_do(call: CallbackQuery, state: FSMContext):
    ok = await promosvc.delete_promo(int(call.data.rsplit(":", 1)[1]))
    await call.answer("Промокод удалён." if ok else "Промокод уже удалён.")
    await promo_list(call, state)
