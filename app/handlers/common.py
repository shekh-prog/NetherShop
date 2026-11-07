from sqlalchemy import select, func
from app.database import Session
from app.models import User

async def get_user(telegram_id):
    async with Session() as s:
        q = await s.execute(select(User).where(User.telegram_id == telegram_id))
        return q.scalar_one_or_none()

async def nick_taken(session, nick: str, exclude_telegram_id: int | None = None) -> bool:
    """Занят ли ник другим пользователем (без учёта регистра).

    .first() вместо scalar_one_or_none(): если в базе уже есть несколько
    «одинаковых» ников (остались от старой версии), запрос не должен падать.
    """
    stmt = select(User.id).where(func.lower(User.minecraft_nick) == nick.lower())
    if exclude_telegram_id is not None:
        stmt = stmt.where(User.telegram_id != exclude_telegram_id)
    return (await session.execute(stmt.limit(1))).first() is not None

async def sync_head_protection(session, telegram_id: int, nick: str) -> None:
    """Держит защиту головы привязанной к аккаунту: при смене ника запись переезжает на новый ник.

    Если админ заранее защитил этот ник как «ничей» (telegram_id пуст) — привязываем его к игроку.
    """
    from app.models import UnsellableHead
    own = (await session.execute(select(UnsellableHead).where(UnsellableHead.telegram_id == telegram_id))).scalars().first()
    other = (await session.execute(select(UnsellableHead).where(
        func.lower(UnsellableHead.nickname) == nick.lower(),
        UnsellableHead.telegram_id.is_(None)))).scalars().first()
    if own and other and other.id != own.id:
        await session.delete(other)   # у игрока уже есть своя запись, она главнее
        await session.flush()
    elif other and not own:
        other.telegram_id = telegram_id
        return
    if own:
        own.nickname = nick
