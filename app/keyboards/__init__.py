from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from app.utils import price_text, MAX_QTY

def main_menu(role: str):
    rows = [[KeyboardButton(text="Сделать заказ"), KeyboardButton(text="Мои заказы")],
            [KeyboardButton(text="Профиль")]]
    if role in ("worker", "admin"):
        rows.append([KeyboardButton(text="Выполнить заказ")])
    if role == "admin":
        rows.append([KeyboardButton(text="Кастомизииировать")])
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
        [InlineKeyboardButton(text=f"Заказ #{o.id} · {o.minecraft_nick}", callback_data=f"worker:order:{o.id}")]
        for o in orders
    ])

def order_actions(order_id: int, status: str, worker_id: int | None, current_worker_id: int):
    rows = []
    if status == "pending":
        rows.append([InlineKeyboardButton(text="Принять", callback_data=f"worker:accept:{order_id}")])
        rows.append([InlineKeyboardButton(text="Отменить", callback_data=f"worker:cancel:{order_id}")])
    if worker_id == current_worker_id and status == "in_progress":
        rows.append([InlineKeyboardButton(text="Заказ готов", callback_data=f"worker:ready:{order_id}")])
        rows.append([InlineKeyboardButton(text="Бросить заказ", callback_data=f"worker:release:{order_id}")])
    if worker_id == current_worker_id and status != "pending":
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
