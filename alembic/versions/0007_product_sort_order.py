"""Product order inside a category (JSON order / manually added go to the bottom)."""
from alembic import op
import sqlalchemy as sa

revision = "0007_product_sort_order"
down_revision = "0006_fsm_states"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("products", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    # Существующие товары сохраняют порядок добавления (раньше они шли по алфавиту).
    op.execute("UPDATE products SET sort_order = id")

def downgrade():
    with op.batch_alter_table("products") as batch:
        batch.drop_column("sort_order")
