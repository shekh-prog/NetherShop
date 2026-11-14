from sqlalchemy import select, func

from app.database import Session
from app.models import Category, Order, PickupPoint, Product, User, CartItem
from app.services import cart as cartsvc

TG = 111


async def seed():
    async with Session() as s:
        s.add(Category(key="gear", button="Экипировка", is_active=True))
        s.add(PickupPoint(name="Спавн", dimension="Обычный мир", x=0, y=64, z=0, is_active=True))
        s.add(User(telegram_id=TG, minecraft_nick="Steve", role="client"))
        p = Product(category="gear", name="Меч", portion_size=1, price_diamonds=10, is_active=True)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id


async def count(model):
    async with Session() as s:
        return await s.scalar(select(func.count()).select_from(model))


async def test_checkout_creates_order_and_clears_cart():
    pid = await seed()
    await cartsvc.set_qty(TG, pid, 3)
    res = await cartsvc.checkout(TG, 1, 1)
    assert res[0] == "ok" and res[2] == 30
    assert await count(Order) == 1
    assert await count(CartItem) == 0


async def test_double_checkout_makes_one_order():
    pid = await seed()
    await cartsvc.set_qty(TG, pid, 1)
    first = await cartsvc.checkout(TG, 1, 1)
    second = await cartsvc.checkout(TG, 1, 1)
    assert first[0] == "ok" and second[0] == "empty"
    assert await count(Order) == 1


async def test_checkout_rolls_back_when_cart_changed(monkeypatch):
    """Корзина изменилась между чтением и оформлением -> заказ не создаётся."""
    pid = await seed()
    await cartsvc.set_qty(TG, pid, 1)
    real_get_cart = cartsvc.get_cart

    async def stale_get_cart(tg_id):
        cart = await real_get_cart(tg_id)
        await cartsvc.clear_cart(tg_id)   # «второй процесс» уже забрал корзину
        return cart

    monkeypatch.setattr(cartsvc, "get_cart", stale_get_cart)
    res = await cartsvc.checkout(TG, 1, 1)
    assert res == ("stale",)
    assert await count(Order) == 0
