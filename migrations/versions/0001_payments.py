from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column("webhook_url", sa.String(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("webhook_delivered_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount > 0", name="ck_payment_amount"),
        sa.CheckConstraint("currency IN ('RUB','USD','EUR')", name="ck_payment_currency"),
        sa.CheckConstraint("status IN ('pending','succeeded','failed')", name="ck_payment_status"),
    )
    op.create_table(
        "outbox",
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_outbox_pending", "outbox", ["created_at"], postgresql_where=sa.text("published_at IS NULL"))


def downgrade():
    op.drop_table("outbox")
    op.drop_table("payments")
