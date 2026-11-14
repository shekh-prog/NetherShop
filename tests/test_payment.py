from sqlalchemy import select, func

from app.database import Session
from app.models import Order, PickupPoint, Sale, User
from app.services import orders as osvc

CLIENT_TG, WORKER_TG = 111, 222


async def seed(total=30, status="ready"):
    async with Session() as s:
        s.add(PickupPoint(name="Спавн", dimension="Обычный мир", x=0, y=64, z=0, is_active=True))
        client = User(telegram_id=CLIENT_TG, minecraft_nick="Steve", role="client")
        worker = User(telegram_id=WORKER_TG, minecraft_nick="Alex", role="worker")
        s.add_all([client, worker])
        await s.flush()
        order = Order(user_id=client.id, worker_id=worker.id, pickup_point_id=1, status=status,
                      total_diamonds=total, items_text="Меч x1")
        s.add(order)
        await s.commit()
        return client.id, worker.id, order.id


async def count(model):
    async with Session() as s:
        return await s.scalar(select(func.count()).select_from(model))


async def test_debt_is_counted_from_ready_and_payment_check_orders():
    client_id, _, order_id = await seed(total=30, status="in_progress")
    assert await osvc.user_debt(client_id) == (0, 0)
    async with Session() as s:
        (await s.get(Order, order_id)).status = "ready"
        await s.commit()
    assert await osvc.user_debt(client_id) == (30, 1)


async def test_claim_moves_order_to_payment_check_and_keeps_it():
    client_id, _, order_id = await seed()
    assert await osvc.claim_order(order_id, client_id) == "payment"
    assert await count(Order) == 1 and await count(Sale) == 0
    assert await osvc.user_debt(client_id) == (30, 1)
    # второй раз «забрать» уже нельзя
    assert await osvc.claim_order(order_id, client_id) is None


async def test_claim_zero_total_closes_immediately():
    client_id, _, order_id = await seed(total=0)
    assert await osvc.claim_order(order_id, client_id) == "done"
    assert await count(Order) == 0 and await count(Sale) == 1


async def test_confirm_payment_closes_order_and_records_sale_once():
    client_id, _, order_id = await seed(status="payment_check")
    assert await osvc.confirm_payment(order_id) == (client_id, 30)
    assert await count(Order) == 0
    assert await osvc.user_debt(client_id) == (0, 0)
    async with Session() as s:
        spent = await s.scalar(select(func.sum(Sale.total_diamonds)).where(Sale.user_id == client_id))
    assert spent == 30
    # повторное подтверждение (второй сотрудник) ничего не пишет
    assert await osvc.confirm_payment(order_id) is None
    assert await count(Sale) == 1


async def test_confirm_payment_ignores_orders_not_waiting_for_payment():
    _, _, order_id = await seed(status="in_progress")
    assert await osvc.confirm_payment(order_id) is None
    assert await count(Order) == 1 and await count(Sale) == 0


async def test_payment_check_visible_to_every_worker():
    _, worker_id, order_id = await seed(status="payment_check")
    async with Session() as s:
        other = User(telegram_id=333, minecraft_nick="Other", role="worker")
        s.add(other)
        await s.commit()
        other_id = other.id
    rows = await osvc.list_worker_orders(other_id)
    assert [o.id for o, _ in rows] == [order_id]


async def test_statistics_split_paid_and_unpaid():
    client_id, _, order_id = await seed(status="payment_check")
    stats = await osvc.sales_statistics()
    assert stats["unpaid"] == (30, 1) and stats["all"] == (0, 0)
    await osvc.confirm_payment(order_id)
    stats = await osvc.sales_statistics()
    assert stats["unpaid"] == (0, 0) and stats["all"] == (30, 1)
