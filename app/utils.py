import re
from datetime import datetime, timezone
from html import escape


def utcnow() -> datetime:
    """Текущее UTC-время без tzinfo (в БД хранятся naive-даты). Замена устаревшему datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

STATUS = {
    "pending": "На рассмотрение",
    "in_progress": "В исполнении",
    "ready": "Прибыл в пункт выдачи",
    "payment_check": "Проверка оплаты",
}

# Статусы, в которых заказ ждёт оплаты: сумма заказа считается долгом клиента.
# Долг не хранится отдельным числом, а считается из заказов — так он не может разойтись с ними
# (отменили заказ или подтвердили оплату — долг исчез сам).
DEBT_STATUSES = ("ready", "payment_check")

def price_text(diamonds: int) -> str:
    blocks = f"{diamonds / 9:.1f}".replace(".", ",")
    return f"{diamonds} алм. ({blocks} аб.)"

def safe(value: str) -> str:
    return escape(str(value))


# Ник Minecraft: только латиница, цифры и «_». Это же гарантирует, что
# сравнение через lower() (в SQLite оно работает только для ASCII) надёжно.
NICK_PLACEHOLDER = "Не указан"
NICK_RE = re.compile(r"[A-Za-z0-9_]{2,32}")
NICK_RULES = "Используй 2–32 символа: латинские буквы, цифры или подчёркивание."

def valid_nick(nick: str) -> bool:
    return bool(NICK_RE.fullmatch(nick or ""))

# Максимум порций одного товара в корзине.
MAX_QTY = 999
