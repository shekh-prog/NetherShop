"""Persistent carts bound to telegram_id; unsellable heads bound to telegram_id."""
from alembic import op
import sqlalchemy as sa

revision = "0004_cart_items"
down_revision = "0003_profiles_heads_bans"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "cart_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("head_nick", sa.String(length=32), nullable=True),
        sa.Column("head_accept", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("telegram_id", "product_id", name="uq_cart_user_product"),
    )
    op.create_index("ix_cart_items_telegram_id", "cart_items", ["telegram_id"])
    op.add_column("unsellable_heads", sa.Column("telegram_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_unsellable_heads_telegram_id", "unsellable_heads", ["telegram_id"])
    # Привязываем уже существующие защищённые головы к зарегистрированным игрокам.
    op.execute(
        "UPDATE unsellable_heads SET telegram_id = ("
        "SELECT users.telegram_id FROM users WHERE lower(users.minecraft_nick) = lower(unsellable_heads.nickname) LIMIT 1)"
    )

def downgrade():
    op.drop_index("ix_unsellable_heads_telegram_id", table_name="unsellable_heads")
    op.drop_column("unsellable_heads", "telegram_id")
    op.drop_index("ix_cart_items_telegram_id", table_name="cart_items")
    op.drop_table("cart_items")
