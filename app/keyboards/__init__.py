from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from app.utils import price_text, MAX_QTY

def main_menu(role: str):
    rows = [[KeyboardButton(text="Сделать заказ"), KeyboardButton(text="Мои заказы")],
            [KeyboardButton(text="Профиль"), KeyboardButton(text="Промокод")]]
    if role in ("worker", "admin"):
        rows.append([KeyboardButton(text="Выполнить заказ")])
    if role == "admin":
        rows.append([KeyboardButton(text="Кастомизировать")])
        rows.append([KeyboardButton(text="Статистика")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def categories_kb(categories):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"cat:{key}")]
        for key, name in categories.items()
    ] + [[InlineKeyboardButton(text="🛒 Корзина", callback_data="cart:view")]])

def heads_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Купить голову", callback_data="heads:buy")],
        [InlineKeyboardButton(text="Сделать мою голову уникальной", callback_data="heads:unique")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="shop:categories")],
    ])

def unique_head_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отправить заявку", callback_data="heads:apply")],
        [InlineKeyboardButton(text="Отменить", callback_data="shop:categories")],
    ])

def profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сменить ник", callback_data="profile:change")]
    ])

def nick_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить", callback_data="profile:confirm"),
         InlineKeyboardButton(text="Отменить", callback_data="profile:cancel")]
    ])

def products_kb(products):
    rows = []
    for p in products:
        label = f"{p.portion_size} шт. · {p.name} · {price_text(p.price_diamonds)}"
        rows.append([InlineKeyboardButton(text=label[:60], callback_data=f"product:{p.id}")])
    rows.append([InlineKeyboardButton(text="🛒 Корзина", callback_data="cart:view")])
    rows.append([InlineKeyboardButton(text="⬅️ Категории", callback_data="shop:categories")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def item_controls(product_id: int, category: str, qty: int, in_cart: bool, has_details: bool):
    """Карточка товара. Кнопки +/- несут готовое новое значение, так что состояние не хранится в памяти."""
    lo = 0 if in_cart else 1
    def step(d):
        return max(lo, min(MAX_QTY, qty + d))
    def btn(label, d):
        return InlineKeyboardButton(text=label, callback_data=f"q:{product_id}:{step(d)}")
    if qty == 0:
        confirm = "🗑 Убрать из корзины"
    elif in_cart:
        confirm = "✅ Обновить корзину"
    else:
        confirm = "Добавить в корзину"
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("−10", -10), btn("−5", -5), btn("−1", -1), btn("+1", 1), btn("+5", 5), btn("+10", 10)],
        [InlineKeyboardButton(text="Изменить подробности" if has_details else "Добавить подробности",
                              callback_data=f"details:{product_id}:{qty}")],
        [InlineKeyboardButton(text=confirm, callback_data=f"add:{product_id}:{qty}")],
        [InlineKeyboardButton(text="🛒 Корзина", callback_data="cart:view"),
         InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cat:{category}")],
    ])

def details_back_kb(product_id: int, qty: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"q:{product_id}:{qty}")]
    ])

def head_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="head:cancel")]
    ])

def head_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить", callback_data="head:confirm"),
         InlineKeyboardButton(text="Отменить", callback_data="head:decline")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="head:cancel")],
    ])

def nick_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="profile:cancel")]
    ])

def clear_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, очистить", callback_data="cart:clear_yes"),
         InlineKeyboardButton(text="Нет", callback_data="cart:view")]
    ])

def cart_kb(cart):
    rows = []
    for item in cart:
        title = item["name"][:34] + ("" if item["available"] else " (недоступно)")
        if item["product_id"] and item["available"]:
            rows.append([InlineKeyboardButton(text=f"✏️ {title}", callback_data=f"product:{item['product_id']}"),
                         InlineKeyboardButton(text="❌", callback_data=f"cart:rm:{item['id']}")])
        else:
            rows.append([InlineKeyboardButton(text=f"❌ Убрать: {title}", callback_data=f"cart:rm:{item['id']}")])
    if cart:
        rows.append([InlineKeyboardButton(text="Оформить заказ", callback_data="cart:checkout")])
        rows.append([InlineKeyboardButton(text="🗑 Очистить всё", callback_data="cart:clear")])
    rows.append([InlineKeyboardButton(text="Продолжить покупки", callback_data="shop:categories")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def pickup_kb(points):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{p.name} · {p.dimension} ({p.x}, {p.y}, {p.z})", callback_data=f"pickup:{p.id}")]
        for p in points
    ])

def worker_orders_kb(orders):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Заказ #{o.id} · {o.minecraft_nick}" + (" · 💰 проверка оплаты" if o.status == "payment_check" else ""),
            callback_data=f"worker:order:{o.id}")]
        for o in orders
    ])

def order_actions(order_id: int, status: str, worker_id: int | None, current_worker_id: int, total_diamonds: int = 1):
    rows = []
    if status == "pending":
        rows.append([InlineKeyboardButton(text="Принять", callback_data=f"worker:accept:{order_id}")])
        rows.append([InlineKeyboardButton(text="Отменить", callback_data=f"worker:cancel:{order_id}")])
    if worker_id == current_worker_id and status == "in_progress":
        rows.append([InlineKeyboardButton(text="Заказ готов", callback_data=f"worker:ready:{order_id}")])
        rows.append([InlineKeyboardButton(text="Бросить заказ", callback_data=f"worker:release:{order_id}")])
    # Оплату подтверждает любой сотрудник, когда клиент уже забрал заказ («Проверка оплаты»).
    # Исполнитель, доставивший заказ, может подтвердить её и раньше — если клиент забыл нажать «Забрал заказ».
    if total_diamonds > 0 and (status == "payment_check" or (status == "ready" and worker_id == current_worker_id)):
        rows.append([InlineKeyboardButton(text="Подтвердить оплату", callback_data=f"worker:paid:{order_id}")])
    # Отменить заказ, который клиент уже забрал, нельзя: иначе долг молча исчезнет.
    if worker_id == current_worker_id and status not in ("pending", "payment_check"):
        rows.append([InlineKeyboardButton(text="Отменить", callback_data=f"worker:cancel:{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="Добавить товар", callback_data="admin:add_product")],
        [InlineKeyboardButton(text="Список товаров", callback_data="admin:products")],
        [InlineKeyboardButton(text="Обновить через файл", callback_data="admin:catalog_file")],
        [InlineKeyboardButton(text="Добавить пункт выдачи", callback_data="admin:add_point")],
        [InlineKeyboardButton(text="Список пунктов", callback_data="admin:points")],
    ])


def my_order_kb(order_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Забрал заказ", callback_data=f"order:claimed:{order_id}")]
    ])


# ---------------------------------------------------------------- промокоды

def _btn(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)

def promo_menu_kb(is_admin: bool):
    rows = [[_btn("Ввести промокод", "promo:enter")], [_btn("Мои промокоды", "promo:mine")]]
    if is_admin:
        rows.append([_btn("Создать промокод", "promo:new")])
        rows.append([_btn("Список промокодов", "promo:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def back_kb(data: str):
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("⬅️ Назад", data)]])

def my_promos_kb(items: list[dict]):
    rows = [[_btn(f"{'🟢' if x['is_active'] else '🔴'} {(x['name'] or x['code'])[:50]}", f"promo:my:{x['rid']}")] for x in items]
    rows.append([_btn("⬅️ Назад", "promo:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def my_promo_view_kb(item: dict):
    rows = []
    if item["used_order_id"] is None:
        if item["is_active"]:
            rows.append([_btn("Деактивировать", f"promo:tg:{item['rid']}:0")])
        else:
            rows.append([_btn("Активировать", f"promo:tg:{item['rid']}:1")])
    rows.append([_btn("⬅️ Назад", "promo:mine")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def promo_cats_kb(categories):
    """Выбор области действия нового промокода: как каталог, но снизу «На всё»."""
    rows = [[_btn(name, f"pn:cat:{key}")] for key, name in categories.items() if key != "heads"]
    rows.append([_btn("На всё", "pn:all")])
    rows.append([_btn("⬅️ Назад", "promo:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def promo_products_kb(products, category: str):
    rows = [[_btn(f"{p.portion_size} шт. · {p.name} · {price_text(p.price_diamonds)}"[:60], f"pn:prod:{p.id}")] for p in products]
    rows.append([_btn("На всё", f"pn:allcat:{category}")])
    rows.append([_btn("⬅️ Назад", "pn:new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def promo_product_confirm_kb(product_id: int, category: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⬅️ Назад", f"pn:cat:{category}"), _btn("Подтвердить", f"pn:ok:{product_id}")]
    ])

def promo_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Отмена", "pn:cancel")]])

def promo_list_kb(promos):
    rows = [[_btn(f"{(p.name or p.code)[:40]} · −{p.percent}%", f"promo:view:{p.id}")] for p in promos]
    rows.append([_btn("⬅️ Назад", "promo:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def promo_view_kb(promo_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🗑 Удалить", f"promo:del:{promo_id}")],
        [_btn("⬅️ Назад", "promo:list")],
    ])

def promo_delete_confirm_kb(promo_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Да, удалить", f"promo:delyes:{promo_id}"), _btn("Нет", f"promo:view:{promo_id}")]
    ])

# ---------------------------------------------------------------- редактор каталога (глава)

def _confirm_label(n: int) -> str:
    return f"✅ Подтвердить ({n})" if n else "✅ Подтвердить"

def ed_cats_kb(categories, n_changes: int):
    rows = [[_btn(name, f"ed:cat:{key}")] for key, name in categories.items() if key != "heads"]
    rows.append([_btn(_confirm_label(n_changes), "ed:ok")])
    rows.append([_btn("Отменить правки и выйти", "ed:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def ed_products_kb(items, n_changes: int):
    """items: список (id, подпись). Подпись уже учитывает ещё не подтверждённые правки."""
    rows = [[_btn(label[:60], f"ed:p:{pid}")] for pid, label in items]
    rows.append([_btn(_confirm_label(n_changes), "ed:ok")])
    rows.append([_btn("⬅️ Категории", "ed:cats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def ed_card_kb(product_id: int, category: str, edited: bool, hidden: bool, n_changes: int):
    rows = [
        [_btn("✏️ Имя", f"ed:f:{product_id}:name"), _btn("💰 Цена", f"ed:f:{product_id}:price"),
         _btn("📦 Шт. в порции", f"ed:f:{product_id}:portion")],
        [_btn("📝 Описание", f"ed:f:{product_id}:desc")],
        [_btn("↩️ Вернуть товар" if hidden else "🗑 Скрыть товар", f"ed:hide:{product_id}")],
    ]
    if edited:
        rows.append([_btn("🔄 Сбросить правки товара", f"ed:reset:{product_id}")])
    rows.append([_btn(_confirm_label(n_changes), "ed:ok")])
    rows.append([_btn("⬅️ Назад", f"ed:cat:{category}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def ed_input_back_kb(product_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("⬅️ Назад", f"ed:p:{product_id}")]])
