from sqlalchemy import select, update, delete, or_, func
from datetime import datetime, timedelta
from sqlalchemy.orm import aliased
from app.database import Session
from app.models import Order, User, PickupPoint, Sale
from app.utils import utcnow, DEBT_STATUSES

async def create_order(user_id, point_id, total, items_text, notes):
    async with Session() as s:
        obj = Order(user_id=user_id, pickup_point_id=point_id, total_diamonds=total,
                    items_text=items_text, notes=notes, status="pending")
        s.add(obj)
        await s.commit()
        await s.refresh(obj)
        return obj.id

async def list_user_orders(user_id):
    async with Session() as s:
        q = await s.execute(select(Order, PickupPoint).join(PickupPoint).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(30))
        return q.all()

async def list_available_orders():
    async with Session() as s:
        q = await s.execute(select(Order, User.minecraft_nick).join(User, User.id == Order.user_id).where(Order.status == "pending").order_by(Order.created_at))
        return [(o, nick) for o, nick in q.all()]

async def get_order(order_id):
    async with Session() as s:
        q = await s.execute(select(Order, User, PickupPoint).join(User, User.id == Order.user_id).join(PickupPoint, PickupPoint.id == Order.pickup_point_id).where(Order.id == order_id))
        return q.first()

async def accept_order(order_id, worker_id):
    async with Session() as s:
        result = await s.execute(update(Order).where(Order.id == order_id, Order.status == "pending", Order.worker_id.is_(None)).values(status="in_progress", worker_id=worker_id))
        await s.commit()
        return result.rowcount == 1

async def release_order(order_id, worker_id):
    async with Session() as s:
        result = await s.execute(update(Order).where(Order.id == order_id, Order.worker_id == worker_id, Order.status == "in_progress").values(status="pending", worker_id=None))
        await s.commit()
        return result.rowcount == 1

async def set_ready(order_id, worker_id):
    async with Session() as s:
        result = await s.execute(update(Order).where(Order.id == order_id, Order.worker_id == worker_id, Order.status == "in_progress").values(status="ready"))
        await s.commit()
        return result.rowcount == 1

async def delete_order(order_id, worker_id):
    async with Session() as s:
        q = await s.execute(select(Order).where(
            Order.id == order_id,
            or_(Order.worker_id == worker_id, (Order.status == "pending") & Order.worker_id.is_(None))
        ))
        obj = q.scalar_one_or_none()
        if not obj:
            return None
        payload = (obj.user_id, obj.items_text, obj.total_diamonds)
        await s.delete(obj)
        await s.commit()
        return payload


async def list_worker_orders(worker_id):
    async with Session() as s:
        q = await s.execute(
            select(Order, User.minecraft_nick).join(User, User.id == Order.user_id)
            # Заказы на проверке оплаты видят все сотрудники: оплату может подтвердить любой из них.
            .where((Order.status == "pending") | (Order.worker_id == worker_id) | (Order.status == "payment_check"))
            .order_by(Order.created_at.desc())
        )
        return [(o, nick) for o, nick in q.all()]


async def claim_order(order_id: int, user_id: int):
    """Клиент нажал «Забрал заказ».

    Заказ с оплатой не удаляется, а переходит в «Проверка оплаты» и остаётся у сотрудников,
    пока кто-то из них не подтвердит оплату (confirm_payment).
    Заказ без суммы (только головы, цена обсуждается в ЛС) закрывается сразу, как раньше.

    Возвращает "payment" | "done" | None (если забрать этот заказ сейчас нельзя).
    """
    async with Session() as s:
        q = await s.execute(select(Order).where(
            Order.id == order_id, Order.user_id == user_id, Order.status == "ready"
        ))
        obj = q.scalar_one_or_none()
        if not obj:
            return None
        if obj.total_diamonds > 0:
            res = await s.execute(update(Order).where(Order.id == order_id, Order.status == "ready")
                                  .values(status="payment_check"))
            await s.commit()
            return "payment" if res.rowcount == 1 else None
        s.add(Sale(total_diamonds=0, completed_at=utcnow(), user_id=obj.user_id))
        await s.delete(obj)
        await s.commit()
        return "done"


async def confirm_payment(order_id: int):
    """Сотрудник подтвердил оплату: заказ исчезает, долг клиента гасится, сумма уходит в продажи клиента и статистику.

    Всё в одной транзакции; удаление с проверкой статуса и rowcount защищает от того,
    что два сотрудника подтвердят один заказ одновременно (продажа запишется один раз).
    Возвращает (user_id, total_diamonds) или None, если заказа нет или он не ждёт оплаты.
    """
    async with Session() as s:
        q = await s.execute(select(Order).where(Order.id == order_id, Order.status.in_(DEBT_STATUSES)))
        obj = q.scalar_one_or_none()
        if not obj or obj.total_diamonds <= 0:
            return None
        user_id, total = obj.user_id, obj.total_diamonds
        res = await s.execute(delete(Order).where(Order.id == order_id, Order.status.in_(DEBT_STATUSES)))
        if res.rowcount != 1:
            await s.rollback()
            return None
        s.add(Sale(total_diamonds=total, completed_at=utcnow(), user_id=user_id))
        await s.commit()
        return user_id, total


async def user_debt(user_id: int) -> tuple[int, int]:
    """Долг клиента: (сумма в алмазах, число неоплаченных заказов)."""
    async with Session() as s:
        row = (await s.execute(
            select(func.coalesce(func.sum(Order.total_diamonds), 0), func.count(Order.id))
            .where(Order.user_id == user_id, Order.status.in_(DEBT_STATUSES))
        )).one()
        return int(row[0] or 0), int(row[1] or 0)


async def sales_statistics():
    now = utcnow()
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)
    async with Session() as s:
        async def totals(since=None):
            stmt = select(func.coalesce(func.sum(Sale.total_diamonds), 0), func.count(Sale.id))
            if since is not None:
                stmt = stmt.where(Sale.completed_at >= since)
            row = (await s.execute(stmt)).one()
            return int(row[0] or 0), int(row[1] or 0)
        week = await totals(week_start)
        month = await totals(month_start)
        all_time = await totals()
        unpaid_row = (await s.execute(
            select(func.coalesce(func.sum(Order.total_diamonds), 0), func.count(Order.id))
            .where(Order.status.in_(DEBT_STATUSES))
        )).one()
        return {"week": week, "month": month, "all": all_time,
                "unpaid": (int(unpaid_row[0] or 0), int(unpaid_row[1] or 0))}
