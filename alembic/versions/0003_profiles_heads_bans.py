"""Add user bans, unsellable heads and per-user sales."""
from alembic import op
import sqlalchemy as sa

revision = "0003_profiles_heads_bans"
down_revision = "0002_sales_username"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("banned_until", sa.DateTime(), nullable=True))
    # SQLite не умеет добавлять внешний ключ обычным ALTER — используем batch-режим.
    with op.batch_alter_table("sales") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_sales_user_id_users", "users", ["user_id"], ["id"])
    op.create_index("ix_sales_user_id", "sales", ["user_id"])
    op.create_table(
        "unsellable_heads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nickname", sa.String(length=32), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_unsellable_heads_nickname", "unsellable_heads", ["nickname"])

def downgrade():
    op.drop_index("ix_unsellable_heads_nickname", table_name="unsellable_heads")
    op.drop_table("unsellable_heads")
    op.drop_index("ix_sales_user_id", table_name="sales")
    with op.batch_alter_table("sales") as batch:
        batch.drop_constraint("fk_sales_user_id_users", type_="foreignkey")
        batch.drop_column("user_id")
    op.drop_column("users", "banned_until")
