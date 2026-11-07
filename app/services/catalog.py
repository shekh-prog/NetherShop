import json
import re
from sqlalchemy import select
from app.database import Session
from app.models import Category, Product

CATEGORY_KEY_RE = re.compile(r"[a-z0-9_-]{1,32}")

async def get_categories() -> dict[str, str]:
    async with Session() as session:
        result = await session.execute(
            select(Category).where(Category.is_active.is_(True)).order_by(Category.key)
        )
        categories = {row.key: row.button for row in result.scalars().all()}
    # Раздел голов системный и не управляется файлом каталога.
    categories["heads"] = "Головы"
    return categories

async def export_catalog() -> bytes:
    async with Session() as session:
        cats_result = await session.execute(
            select(Category).where(Category.is_active.is_(True)).order_by(Category.key)
        )
        categories = cats_result.scalars().all()
        data = {}
        for category in categories:
            products_result = await session.execute(
                select(Product).where(
                    Product.category == category.key, Product.is_active.is_(True)
                ).order_by(Product.name)
            )
            data[category.key] = {
                "button": category.button,
                "items": [
                    [product.name, product.portion_size, product.price_diamonds]
                    for product in products_result.scalars().all()
                ],
            }
    def format_json(value, level=0):
        pad = "  " * level
        child_pad = "  " * (level + 1)
        if isinstance(value, dict):
            if not value:
                return "{}"
            lines = ["{"]
            entries = list(value.items())
            for index, (key, item_value) in enumerate(entries):
                comma = "," if index < len(entries) - 1 else ""
                key_json = json.dumps(key, ensure_ascii=False)
                lines.append(f"{child_pad}{key_json}: {format_json(item_value, level + 1)}{comma}")
            lines.append(f"{pad}}}")
            return "\n".join(lines)
        if isinstance(value, list):
            # Массивы со скалярными значениями (название, порция, цена)
            # оставляем в одну строку для удобного ручного редактирования.
            if all(not isinstance(item, (dict, list)) for item in value):
                return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in value) + "]"
            if not value:
                return "[]"
            lines = ["["]
            for index, item in enumerate(value):
                comma = "," if index < len(value) - 1 else ""
                lines.append(f"{child_pad}{format_json(item, level + 1)}{comma}")
            lines.append(f"{pad}]")
            return "\n".join(lines)
        return json.dumps(value, ensure_ascii=False)

    return (format_json(data) + "\n").encode("utf-8")

def validate_catalog(data):
    if not isinstance(data, dict) or not data:
        raise ValueError("В корне JSON должен находиться непустой объект категорий.")
    clean = {}
    for key, category in data.items():
        if not isinstance(key, str) or not CATEGORY_KEY_RE.fullmatch(key) or key == "heads":
            raise ValueError(f"Некорректный ключ категории: {key!r}. Используй латиницу, цифры, _ или - (до 32 символов).")
        if not isinstance(category, dict):
            raise ValueError(f"Категория {key}: ожидается объект с полями button и items.")
        button = category.get("button")
        items = category.get("items")
        if not isinstance(button, str) or not button.strip() or len(button.strip()) > 64:
            raise ValueError(f"Категория {key}: поле button должно содержать название от 1 до 64 символов.")
        if not isinstance(items, list):
            raise ValueError(f"Категория {key}: поле items должно быть списком.")
        clean_items = []
        names = set()
        for index, item in enumerate(items, 1):
            if not isinstance(item, list) or len(item) != 3:
                raise ValueError(f"Категория {key}, товар №{index}: ожидается массив [название, количество, цена].")
            name, portion, price = item
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
                raise ValueError(f"Категория {key}, товар №{index}: некорректное название (1–120 символов).")
            if type(portion) is not int or not 1 <= portion <= 2147483647:
                raise ValueError(f"Товар {name}: количество должно быть положительным целым числом.")
            if type(price) is not int or not 0 <= price <= 2147483647:
                raise ValueError(f"Товар {name}: цена должна быть неотрицательным целым числом.")
            name = name.strip()
            if name.casefold() in names:
                raise ValueError(f"В категории {key} повторяется товар {name}.")
            names.add(name.casefold())
            clean_items.append((name, portion, price))
        clean[key] = {"button": button.strip(), "items": clean_items}
    return clean

async def apply_catalog(data):
    clean = validate_catalog(data)
    async with Session() as session:
        # Изменения применяются одной транзакцией: ошибка не оставит частично обновлённый каталог.
        for key, category_data in clean.items():
            category = await session.get(Category, key)
            if category is None:
                session.add(Category(key=key, button=category_data["button"], is_active=True))
            else:
                category.button = category_data["button"]
                category.is_active = True

            incoming_names = set()
            for name, portion, price in category_data["items"]:
                incoming_names.add(name.casefold())
                result = await session.execute(
                    select(Product).where(Product.category == key, Product.name == name)
                )
                product = result.scalar_one_or_none()
                if product is None:
                    session.add(Product(category=key, name=name, portion_size=portion,
                                        price_diamonds=price, description=None, is_active=True))
                else:
                    product.portion_size = portion
                    product.price_diamonds = price
                    product.is_active = True

            existing = await session.execute(select(Product).where(Product.category == key, Product.is_active.is_(True)))
            for product in existing.scalars().all():
                if product.name.casefold() not in incoming_names:
                    product.is_active = False

        # Категории, исключённые из файла, и их товары скрываются, но не удаляются физически.
        for category in (await session.execute(select(Category))).scalars().all():
            if category.key not in clean:
                category.is_active = False
                products = await session.execute(select(Product).where(Product.category == category.key))
                for product in products.scalars().all():
                    product.is_active = False
        # Любые товары в неизвестных/неактивных категориях также скрываются.
        await session.commit()
    return sum(len(value["items"]) for value in clean.values()), len(clean)

def parse_catalog_json(raw: bytes):
    try:
        decoded = raw.decode("utf-8-sig")
        data = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Не удалось прочитать JSON. Проверь кодировку UTF-8 и синтаксис файла.") from exc
    # Валидация выполняется в apply_catalog(). Возвращаем исходные JSON-списки,
    # иначе повторная проверка примет нормализованные tuple за неверный формат.
    return data
