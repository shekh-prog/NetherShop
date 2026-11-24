"""Промокоды: создание, ввод игроком, активация/деактивация, расчёт скидки."""
import asyncio
import html
import re
import secrets
import string

from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError

from app.database import Session
from app.models import PromoCode, PromoRedemption, Product, Category
from app.utils import utcnow

CODE_RE = re.compile(r"[A-Za-z0-9_-]{3,32}")
_locks: dict[int, asyncio.Lock] = {}


def _lock(user_id: int) -> asyncio.Lock:
    return _locks.setdefault(user_id, asyncio.Lock())


def random_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


def promo_title(promo) -> str:
    """Название для показа игроку (если названия нет — сам код). Принимает и модель, и dict активации."""
    if isinstance(promo, dict):
        return promo.get("name") or promo["code"]
    return promo.name or promo.code


async def create_promo(scope: str, category: str | None, product_id: int | None, percent: int,
                       name: str | None, code: str | None, max_uses: int) -> PromoCode | None:
    """Создаёт промокод. code=None — случайный (12 символов A-Z0-9). Возвращает None, если такой код уже занят."""
    async with Session() as s:
        if code is None:
            for _ in range(50):
                candidate = random_code()
                if (await s.execute(select(PromoCode.id).where(PromoCode.code == candidate))).first() is None:
                    code = candidate
                    break
            else:
                return None
        else:
            code = code.upper()
            if (await s.execute(select(PromoCode.id).where(PromoCode.code == code))).first() is not None:
                return None
        promo = PromoCode(code=code, name=name, scope=scope, category=category, product_id=product_id,
                          percent=percent, max_uses=max_uses, uses=0)
        s.add(promo)
        try:
            await s.commit()
        except IntegrityError:
            return None
        return promo


async def code_exists(code: str) -> bool:
    async with Session() as s:
        return (await s.execute(select(PromoCode.id).where(PromoCode.code == code.upper()))).first() is not None


async def list_promos() -> list[PromoCode]:
    async with Session() as s:
        return list((await s.execute(select(PromoCode).order_by(PromoCode.id.desc()))).scalars().all())


async def get_promo(promo_id: int) -> PromoCode | None:
    async with Session() as s:
        return await s.get(PromoCode, promo_id)


async def delete_promo(promo_id: int) -> bool:
    """Удаляет промокод из базы вместе с активациями игроков (у них он пропадает из «Моих промокодов»)."""
    async with Session() as s:
        promo = await s.get(PromoCode, promo_id)
        if not promo:
            return False
        await s.execute(delete(PromoRedemption).where(PromoRedemption.promo_id == promo_id))
        await s.delete(promo)
        await s.commit()
        return True


async def redeem(user_id: int, raw_code: str):
    """Игрок ввёл промокод.

    Возвращает (результат, промокод): ok | not_found | already | has_active | exhausted.
    Счётчик использований растёт в момент ввода кода (атомарно, чтобы лимит нельзя было превысить);
    у игрока может быть только один активный промокод, стакать их нельзя.
    """
    code = (raw_code or "").strip().upper()
    async with _lock(user_id):
        try:
            async with Session() as s, s.begin():
                promo = (await s.execute(select(PromoCode).where(PromoCode.code == code))).scalar_one_or_none()
                if not promo:
                    return "not_found", None
                if (await s.execute(select(PromoRedemption.id).where(
                        PromoRedemption.promo_id == promo.id, PromoRedemption.user_id == user_id))).first():
                    return "already", promo
                if (await s.execute(select(PromoRedemption.id).where(
                        PromoRedemption.user_id == user_id, PromoRedemption.is_active.is_(True)))).first():
                    return "has_active", promo
                res = await s.execute(update(PromoCode).where(
                    PromoCode.id == promo.id, PromoCode.uses < PromoCode.max_uses
                ).values(uses=PromoCode.uses + 1))
                if res.rowcount != 1:
                    return "exhausted", promo
                s.add(PromoRedemption(promo_id=promo.id, user_id=user_id, is_active=True))
        except IntegrityError:
            # Сработал уникальный индекс: параллельный запрос успел активировать другой промокод.
            return "has_active", None
        return "ok", promo


def _promo_dict(redemption: PromoRedemption, promo: PromoCode) -> dict:
    return dict(rid=redemption.id, promo_id=promo.id, code=promo.code, name=promo.name, scope=promo.scope,
                category=promo.category, product_id=promo.product_id, percent=promo.percent,
                is_active=redemption.is_active, used_order_id=redemption.used_order_id)


async def get_active_promo(user_id: int) -> dict | None:
    async with Session() as s:
        row = (await s.execute(
            select(PromoRedemption, PromoCode).join(PromoCode, PromoCode.id == PromoRedemption.promo_id)
            .where(PromoRedemption.user_id == user_id, PromoRedemption.is_active.is_(True))
        )).first()
    return _promo_dict(*row) if row else None


async def list_user_promos(user_id: int) -> list[dict]:
    async with Session() as s:
        rows = (await s.execute(
            select(PromoRedemption, PromoCode).join(PromoCode, PromoCode.id == PromoRedemption.promo_id)
            .where(PromoRedemption.user_id == user_id).order_by(PromoRedemption.id.desc())
        )).all()
    return [_promo_dict(r, p) for r, p in rows]


async def get_user_promo(rid: int, user_id: int) -> dict | None:
    async with Session() as s:
        row = (await s.execute(
            select(PromoRedemption, PromoCode).join(PromoCode, PromoCode.id == PromoRedemption.promo_id)
            .where(PromoRedemption.id == rid, PromoRedemption.user_id == user_id)
        )).first()
    return _promo_dict(*row) if row else None


async def set_active(rid: int, user_id: int, active: bool) -> str:
    """Включает/выключает промокод игрока. Возвращает ok | missing | used | conflict."""
    async with _lock(user_id):
        try:
            async with Session() as s, s.begin():
                red = (await s.execute(select(PromoRedemption).where(
                    PromoRedemption.id == rid, PromoRedemption.user_id == user_id))).scalar_one_or_none()
                if not red:
                    return "missing"
                if red.used_order_id is not None:
                    return "used"
                if active and not red.is_active:
                    other = (await s.execute(select(PromoRedemption.id).where(
                        PromoRedemption.user_id == user_id, PromoRedemption.is_active.is_(True),
                        PromoRedemption.id != rid))).first()
                    if other:
                        return "conflict"
                red.is_active = active
        except IntegrityError:
            return "conflict"
        return "ok"


def compute_discount(cart: list[dict], promo: dict | None) -> tuple[int, int]:
    """(сумма подходящих позиций, размер скидки в алмазах). Скидка округляется вниз."""
    if not promo:
        return 0, 0
    subtotal = 0
    for x in cart:
        if not x["available"] or x["product_id"] is None:
            continue
        if promo["scope"] == "category" and x.get("category") != promo["category"]:
            continue
        if promo["scope"] == "product" and x["product_id"] != promo["product_id"]:
            continue
        subtotal += x["price"] * x["qty"]
    return subtotal, subtotal * promo["percent"] // 100


async def scope_text(promo) -> str:
    """Человеческое описание, на что действует промокод (promo — модель или dict)."""
    get = (lambda k: promo[k]) if isinstance(promo, dict) else (lambda k: getattr(promo, k))
    scope = get("scope")
    if scope == "all":
        return "на все товары"
    async with Session() as s:
        if scope == "category":
            cat = await s.get(Category, get("category"))
            return f"на категорию «{html.escape(cat.button if cat else get('category'))}»"
        product = await s.get(Product, get("product_id"))
        return f"на товар «{html.escape(product.name if product else 'удалённый товар')}»"
