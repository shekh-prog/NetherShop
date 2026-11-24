from sqlalchemy import select, func

from app.database import Session
from app.models import Category, Order, PickupPoint, Product, PromoRedemption, Sale, User
from app.services import cart as cartsvc
from app.services import promo as promosvc
from app.services import orders as osvc

TG1, TG2 = 111, 222


async def seed():
    """Два игрока, товар «Меч» (10 алм.) в категории gear, пункт выдачи."""
    async with Session() as s:
        s.add(Category(key="gear", button="Экипировка", is_active=True))
        s.add(Category(key="food", button="Еда", is_active=True))
        s.add(PickupPoint(name="Спавн", dimension="Обычный мир", x=0, y=64, z=0, is_active=True))
        u1 = User(telegram_id=TG1, minecraft_nick="Steve", role="client")
        u2 = User(telegram_id=TG2, minecraft_nick="Alex", role="client")
        sword = Product(category="gear", name="Меч", portion_size=1, price_diamonds=10, is_active=True)
        bread = Product(category="food", name="Хлеб", portion_size=16, price_diamonds=4, is_active=True)
        s.add_all([u1, u2, sword, bread])
        await s.commit()
        return u1.id, u2.id, sword.id, bread.id


async def make_promo(scope="all", category=None, product_id=None, percent=50, code="TEST1", max_uses=5):
    return await promosvc.create_promo(scope, category, product_id, percent, None, code, max_uses)


async def test_random_code_format_and_uniqueness():
    promo = await promosvc.create_promo("all", None, None, 10, "Скидка", None, 3)
    assert len(promo.code) == 12 and promo.code == promo.code.upper()
    assert all(c.isdigit() or ("A" <= c <= "Z") for c in promo.code)
    assert await make_promo(code=promo.code.lower()) is None      # такой код уже есть (регистр не важен)


async def test_redeem_rules():
    u1, u2, *_ = await seed()
    await make_promo(code="ONE", max_uses=1)
    assert (await promosvc.redeem(u1, "nope"))[0] == "not_found"
    assert (await promosvc.redeem(u1, " one "))[0] == "ok"           # регистр и пробелы не важны
    assert (await promosvc.redeem(u1, "ONE"))[0] == "already"        # один игрок — один раз
    assert (await promosvc.redeem(u2, "ONE"))[0] == "exhausted"      # лимит на всех игроков


async def test_no_stacking_and_toggle():
    u1, *_ = await seed()
    await make_promo(code="A1")
    await make_promo(code="B2")
    assert (await promosvc.redeem(u1, "A1"))[0] == "ok"
    assert (await promosvc.redeem(u1, "B2"))[0] == "has_active"      # второй активировать нельзя
    mine = await promosvc.list_user_promos(u1)
    assert len(mine) == 1 and mine[0]["is_active"]
    assert await promosvc.set_active(mine[0]["rid"], u1, False) == "ok"
    assert (await promosvc.redeem(u1, "B2"))[0] == "ok"              # после деактивации можно вводить другой
    # включить первый обратно, пока активен второй, нельзя
    assert await promosvc.set_active(mine[0]["rid"], u1, True) == "conflict"
    async with Session() as s:
        active = await s.scalar(select(func.count()).select_from(PromoRedemption)
                                .where(PromoRedemption.user_id == u1, PromoRedemption.is_active.is_(True)))
    assert active == 1


def test_compute_discount_scopes():
    cart = [dict(id=1, product_id=1, category="gear", price=10, qty=3, available=True),
            dict(id=2, product_id=2, category="food", price=4, qty=5, available=True),
            dict(id=3, product_id=None, category=None, price=0, qty=1, available=True)]
    base = dict(code="X", name=None, percent=50, is_active=True, used_order_id=None, rid=1, promo_id=1)
    assert promosvc.compute_discount(cart, dict(base, scope="all", category=None, product_id=None)) == (50, 25)
    assert promosvc.compute_discount(cart, dict(base, scope="category", category="food", product_id=None)) == (20, 10)
    assert promosvc.compute_discount(cart, dict(base, scope="product", category=None, product_id=1)) == (30, 15)
    assert promosvc.compute_discount(cart, dict(base, scope="product", category=None, product_id=99)) == (0, 0)
    assert promosvc.compute_discount(cart, None) == (0, 0)


async def test_checkout_applies_discount_and_consumes_promo():
    u1, _, sword, _ = await seed()
    await make_promo(scope="product", product_id=sword, percent=50, code="HALF")
    await promosvc.redeem(u1, "HALF")
    await cartsvc.set_qty(TG1, sword, 3)                              # 30 алм. -> скидка 15
    res = await cartsvc.checkout(TG1, u1, 1)
    assert res[0] == "ok" and res[2] == 15 and res[4] == 15
    async with Session() as s:
        order = (await s.execute(select(Order))).scalar_one()
        red = (await s.execute(select(PromoRedemption))).scalar_one()
    assert order.total_diamonds == 15 and "HALF" in order.items_text
    assert not red.is_active and red.used_order_id == order.id
    # промокод сгорел: следующий заказ без скидки
    await cartsvc.set_qty(TG1, sword, 1)
    assert (await cartsvc.checkout(TG1, u1, 1))[2] == 10


async def test_promo_not_consumed_when_it_matches_nothing():
    u1, _, sword, bread = await seed()
    await make_promo(scope="category", category="food", percent=20, code="FOOD")
    await promosvc.redeem(u1, "FOOD")
    await cartsvc.set_qty(TG1, sword, 1)
    res = await cartsvc.checkout(TG1, u1, 1)
    assert res[2] == 10 and res[4] == 0
    assert (await promosvc.get_active_promo(u1)) is not None          # остался активным


async def test_full_discount_goes_to_database_as_zero():
    u1, _, sword, _ = await seed()
    await make_promo(percent=100, code="FREE")
    await promosvc.redeem(u1, "FREE")
    await cartsvc.set_qty(TG1, sword, 2)
    res = await cartsvc.checkout(TG1, u1, 1)
    assert res[2] == 0
    async with Session() as s:
        order_id = (await s.execute(select(Order.id))).scalar_one()
    async with Session() as s:
        (await s.get(Order, order_id)).status = "ready"
        await s.commit()
    assert await osvc.claim_order(order_id, u1) == "done"             # сумма 0 -> закрывается сразу
    async with Session() as s:
        sales = (await s.execute(select(Sale.total_diamonds))).scalars().all()
    assert sales == [0]


async def test_cancelled_order_returns_promo():
    u1, _, sword, _ = await seed()
    await make_promo(percent=50, code="BACK")
    await promosvc.redeem(u1, "BACK")
    await cartsvc.set_qty(TG1, sword, 2)
    res = await cartsvc.checkout(TG1, u1, 1)
    assert await promosvc.get_active_promo(u1) is None
    assert await osvc.delete_order(res[1], worker_id=999) is not None   # pending-заказ без исполнителя
    back = await promosvc.get_active_promo(u1)
    assert back is not None and back["code"] == "BACK" and back["used_order_id"] is None


async def test_delete_promo_removes_redemptions():
    u1, *_ = await seed()
    promo = await make_promo(code="GONE")
    await promosvc.redeem(u1, "GONE")
    assert await promosvc.delete_promo(promo.id)
    assert await promosvc.list_user_promos(u1) == []
    assert (await promosvc.redeem(u1, "GONE"))[0] == "not_found"


async def test_manual_balance_rows_count_in_sum_but_not_in_orders():
    u1, *_ = await seed()
    async with Session() as s:
        s.add(Sale(total_diamonds=30, user_id=u1))
        s.add(Sale(total_diamonds=20, user_id=u1, is_manual=True))
        s.add(Sale(total_diamonds=-5, user_id=u1, is_manual=True))
        await s.commit()
    stats = await osvc.sales_statistics()
    assert stats["all"] == (45, 1)


async def test_title_and_scope_text_work_for_active_promo_dict():
    """Регресс: меню промокодов и корзина падали, когда у игрока был активный промокод (dict, а не модель)."""
    u1, *_ = await seed()
    promo = await promosvc.create_promo("category", "gear", None, 50, None, "BLOCKS", 5)
    await promosvc.redeem(u1, "BLOCKS")
    active = await promosvc.get_active_promo(u1)
    assert promosvc.promo_title(active) == "BLOCKS"
    assert promosvc.promo_title(promo) == "BLOCKS"
    assert "Экипировка" in await promosvc.scope_text(active)
    assert "Экипировка" in await promosvc.scope_text(promo)


async def test_scope_text_escapes_html():
    """Названия вставляются в HTML-сообщения Telegram: «&» и «<» должны быть экранированы."""
    async with Session() as s:
        s.add(Category(key="mix", button="Блоки & декор <new>", is_active=True))
        await s.commit()
    text = await promosvc.scope_text(dict(scope="category", category="mix", product_id=None))
    assert "&amp;" in text and "<new>" not in text and "&lt;new&gt;" in text
