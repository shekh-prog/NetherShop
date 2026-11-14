import pytest
from sqlalchemy import select

from app.database import Session
from app.models import Category, Product
from app.services.catalog import apply_catalog, export_catalog, validate_catalog


def catalog(*items, key="gear"):
    return {key: {"button": "Экипировка", "items": [list(i) for i in items]}}


def test_validate_rejects_bad_data():
    with pytest.raises(ValueError):
        validate_catalog({})
    with pytest.raises(ValueError):
        validate_catalog({"heads": {"button": "x", "items": []}})
    with pytest.raises(ValueError):
        validate_catalog(catalog(["Меч", 0, 5]))
    with pytest.raises(ValueError):
        validate_catalog(catalog(["Меч", 1, 5], ["меч", 1, 6]))


async def test_apply_creates_and_hides():
    await apply_catalog(catalog(["Алмазный меч", 1, 32], ["Берёза", 64, 2]))
    await apply_catalog(catalog(["Алмазный меч", 1, 40]))
    async with Session() as s:
        products = {p.name: p for p in (await s.execute(select(Product))).scalars()}
    assert products["Алмазный меч"].price_diamonds == 40 and products["Алмазный меч"].is_active
    assert not products["Берёза"].is_active


async def test_apply_survives_duplicate_names():
    """Скрыли товар и создали такой же заново -> две строки с одним названием."""
    async with Session() as s:
        s.add(Category(key="gear", button="Экипировка", is_active=True))
        s.add(Product(category="gear", name="Алмазный меч", portion_size=1, price_diamonds=30, is_active=False))
        s.add(Product(category="gear", name="Алмазный меч", portion_size=1, price_diamonds=31, is_active=True))
        await s.commit()
    await apply_catalog(catalog(["Алмазный меч", 1, 50]))
    async with Session() as s:
        rows = (await s.execute(select(Product))).scalars().all()
    active = [p for p in rows if p.is_active]
    assert len(active) == 1 and active[0].price_diamonds == 50


async def test_export_roundtrip():
    await apply_catalog(catalog(["Берёза", 64, 2]))
    raw = await export_catalog()
    assert "Берёза" in raw.decode("utf-8")


async def active_names():
    async with Session() as s:
        rows = (await s.execute(
            select(Product).where(Product.is_active.is_(True)).order_by(Product.sort_order, Product.id)
        )).scalars().all()
    return [p.name for p in rows]


async def test_json_order_is_kept_and_follows_reorder():
    await apply_catalog(catalog(["Яблоко", 1, 1], ["Арбуз", 1, 2], ["Берёза", 1, 3]))
    assert await active_names() == ["Яблоко", "Арбуз", "Берёза"]   # не по алфавиту
    await apply_catalog(catalog(["Берёза", 1, 3], ["Яблоко", 1, 1], ["Арбуз", 1, 2]))
    assert await active_names() == ["Берёза", "Яблоко", "Арбуз"]


async def test_export_keeps_order():
    await apply_catalog(catalog(["Яблоко", 1, 1], ["Арбуз", 1, 2]))
    raw = (await export_catalog()).decode("utf-8")
    assert raw.index("Яблоко") < raw.index("Арбуз")
