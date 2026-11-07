"""Add Telegram usernames and completed sales ledger."""
from alembic import op
import sqlalchemy as sa

revision = "0002_sales_username"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("telegram_username", sa.String(length=64), nullable=True))
    op.create_table(
        "sales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("total_diamonds", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sales_completed_at", "sales", ["completed_at"])

def downgrade():
    op.drop_index("ix_sales_completed_at", table_name="sales")
    op.drop_table("sales")
    op.drop_column("users", "telegram_username")
