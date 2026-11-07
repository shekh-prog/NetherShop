"""Persist editable catalog category names."""
from alembic import op
import sqlalchemy as sa

revision = "0005_categories"
down_revision = "0004_cart_items"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "categories",
        sa.Column("key", sa.String(length=32), primary_key=True),
        sa.Column("button", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.bulk_insert(
        sa.table("categories", sa.column("key", sa.String), sa.column("button", sa.String), sa.column("is_active", sa.Boolean)),
        [
            {"key": "gear", "button": "Экипировка и ПвП", "is_active": True},
            {"key": "blocks", "button": "Блоки", "is_active": True},
            {"key": "other", "button": "Другие ресурсы", "is_active": True},
        ],
    )

def downgrade():
    op.drop_table("categories")
