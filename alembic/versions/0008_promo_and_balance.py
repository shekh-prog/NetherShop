"""Promo codes, manual balance adjustments (sales.is_manual), orders.promo_redemption_id."""
from alembic import op
import sqlalchemy as sa

revision = "0008_promo_and_balance"
down_revision = "0007_product_sort_order"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("sales", sa.Column("is_manual", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("orders", sa.Column("promo_redemption_id", sa.Integer(), nullable=True))
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_promo_codes_code", "promo_codes", ["code"], unique=True)
    op.create_table(
        "promo_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("promo_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("used_order_id", sa.Integer(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("promo_id", "user_id", name="uq_promo_user"),
    )
    op.create_index("ix_promo_redemptions_promo_id", "promo_redemptions", ["promo_id"])
    op.create_index("ix_promo_redemptions_user_id", "promo_redemptions", ["user_id"])
    op.create_index("uq_promo_active_per_user", "promo_redemptions", ["user_id"], unique=True,
                    sqlite_where=sa.text("is_active = 1"))

def downgrade():
    op.drop_table("promo_redemptions")
    op.drop_table("promo_codes")
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("promo_redemption_id")
    with op.batch_alter_table("sales") as batch:
        batch.drop_column("is_manual")
