"""Persistent FSM storage (dialog states survive bot restarts)."""
from alembic import op
import sqlalchemy as sa

revision = "0006_fsm_states"
down_revision = "0005_categories"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "fsm_states",
        sa.Column("key", sa.String(length=200), primary_key=True),
        sa.Column("state", sa.String(length=200), nullable=True),
        sa.Column("data", sa.Text(), nullable=False, server_default="{}"),
    )

def downgrade():
    op.drop_table("fsm_states")
