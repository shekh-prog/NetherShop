from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, Boolean, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.utils import utcnow

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    minecraft_nick: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16), default="client")
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    banned_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Category(Base):
    __tablename__ = "categories"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    button: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    portion_size: Mapped[int] = mapped_column(Integer)
    price_diamonds: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Порядок внутри категории: из JSON — как в файле, добавленные вручную — в самый низ.
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

class PickupPoint(Base):
    __tablename__ = "pickup_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    dimension: Mapped[str] = mapped_column(String(32))
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    z: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    pickup_point_id: Mapped[int] = mapped_column(ForeignKey("pickup_points.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    total_diamonds: Mapped[int] = mapped_column(Integer)
    items_text: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Sale(Base):
    """Revenue-only record; order details are not retained after pickup."""
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    total_diamonds: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

class UnsellableHead(Base):
    __tablename__ = "unsellable_heads"
    id: Mapped[int] = mapped_column(primary_key=True)
    nickname: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # Привязка к Telegram-аккаунту: защита головы переживает смену ника.
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CartItem(Base):
    """Позиция корзины. Корзина привязана к telegram_id, а не к нику, и хранится в БД."""
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("telegram_id", "product_id", name="uq_cart_user_product"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)  # NULL — голова
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    head_nick: Mapped[str | None] = mapped_column(String(32), nullable=True)
    head_accept: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FsmState(Base):
    """Состояние диалогов (FSM) переживает перезапуск бота."""
    __tablename__ = "fsm_states"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    state: Mapped[str | None] = mapped_column(String(200), nullable=True)
    data: Mapped[str] = mapped_column(Text, default="{}")
