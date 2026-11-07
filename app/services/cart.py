"""Корзина в БД, привязанная к telegram_id (не зависит ни от ника, ни от FSM)."""
import asyncio
from sqlalchemy import select, delete, func
from app.database import Session
from app.models import CartItem, Product
from app.utils import MAX_QTY
from app.services.orders import create_order

_locks: dict[int, asyncio.Lock] = {}

async def get_cart(tg_id: int) -> list[dict]:
    async with Session() as s:
        items = (await s.execute(select(CartItem).where(CartItem.telegram_id == tg_id).order_by(CartItem.id))).scalars().all()
        pids = {i.product_id for i in items if i.product_id}
        prods = {}
        if pids:
            prods = {p.id: p for p in (await s.execute(select(Product).where(Product.id.in_(pids)))).scalars()}
    lines = []
    for i in items:
        if i.product_id is None:
            lines.append(dict(id=i.id, product_id=None, name=f"Голова игрока {i.head_nick}", portion=1, price=0,
                              qty=1, details="", head_nick=i.head_nick, head_accept=i.head_accept, available=True))
        else:
            p = prods.get(i.product_id)
            lines.append(dict(id=i.id, product_id=i.product_id, name=p.name if p else "Товар удалён",
                              portion=p.portion_size if p else 0, price=p.price_diamonds if p else 0,
                              qty=i.quantity, details=i.details or "", head_nick=None, head_accept=False,
                              available=bool(p and p.is_active)))
    return lines

def cart_total(cart: list[dict]) -> int:
    return sum(x["price"] * x["qty"] for x in cart if x["available"])

async def get_line(tg_id: int, product_id: int) -> tuple[int, str]:
    """(порций в корзине, подробности); (0, "") если товара в корзине нет."""
    async with Session() as s:
        it = (await s.execute(select(CartItem).where(CartItem.telegram_id == tg_id,
                                                     CartItem.product_id == product_id))).scalars().first()
    return (it.quantity, it.details or "") if it else (0, "")

async def set_qty(tg_id: int, product_id: int, qty: int, details: str | None = None) -> None:
    """Устанавливает (а не прибавляет!) количество. qty <= 0 убирает позицию. details=None — не менять."""
    async with Session() as s:
        it = (await s.execute(select(CartItem).where(CartItem.telegram_id == tg_id,
                                                     CartItem.product_id == product_id))).scalars().first()
        if qty <= 0:
            if it:
                await s.delete(it)
        else:
            qty = min(qty, MAX_QTY)
            if it:
                it.quantity = qty
                if details is not None:
                    it.details = details or None
            else:
                s.add(CartItem(telegram_id=tg_id, product_id=product_id, quantity=qty, details=details or None))
        await s.commit()

async def set_details(tg_id: int, product_id: int, details: str) -> bool:
    async with Session() as s:
        it = (await s.execute(select(CartItem).where(CartItem.telegram_id == tg_id,
                                                     CartItem.product_id == product_id))).scalars().first()
        if not it:
            return False
        it.details = details or None
        await s.commit()
        return True

async def add_head(tg_id: int, nick: str, accepted: bool) -> None:
    async with Session() as s:
        it = (await s.execute(select(CartItem).where(CartItem.telegram_id == tg_id, CartItem.product_id.is_(None),
                                                     func.lower(CartItem.head_nick) == nick.lower()))).scalars().first()
        if it:
            it.head_accept = accepted
        else:
            s.add(CartItem(telegram_id=tg_id, product_id=None, quantity=1, head_nick=nick, head_accept=accepted))
        await s.commit()

async def remove_item(tg_id: int, item_id: int) -> None:
    async with Session() as s:
        await s.execute(delete(CartItem).where(CartItem.id == item_id, CartItem.telegram_id == tg_id))
        await s.commit()

async def clear_cart(tg_id: int) -> None:
    async with Session() as s:
        await s.execute(delete(CartItem).where(CartItem.telegram_id == tg_id))
        await s.commit()

async def purge_unavailable(tg_id: int) -> int:
    """Убирает позиции, чей товар скрыт/удалён из каталога. Возвращает, сколько убрано."""
    bad = [x["id"] for x in await get_cart(tg_id) if not x["available"]]
    if bad:
        async with Session() as s:
            await s.execute(delete(CartItem).where(CartItem.id.in_(bad), CartItem.telegram_id == tg_id))
            await s.commit()
    return len(bad)

def order_text(cart: list[dict]) -> str:
    items = []
    for x in cart:
        line = f"{x['qty']} порц. × {x['name']} ({x['portion']} шт./порция)"
        if x.get("details"): line += f"; детали: {x['details']}"
        if x.get("head_nick"): line += f"; голова: {x['head_nick']}; ответственность: {'принята' if x.get('head_accept') else 'не принята'}"
        items.append(line)
    return "\n".join(items)

async def checkout(tg_id: int, user_id: int, point_id: int):
    """Оформление заказа из корзины. Блокировка на пользователя защищает от двойного нажатия.

    Возвращает ("empty",) | ("changed",) | ("ok", order_id, total, items_text).
    """
    lock = _locks.setdefault(tg_id, asyncio.Lock())
    async with lock:
        cart = await get_cart(tg_id)
        if not cart:
            return ("empty",)
        if any(not x["available"] for x in cart):
            await purge_unavailable(tg_id)
            return ("changed",)
        total = cart_total(cart)
        text = order_text(cart)
        order_id = await create_order(user_id, point_id, total, text, "")
        await clear_cart(tg_id)
        return ("ok", order_id, total, text)
