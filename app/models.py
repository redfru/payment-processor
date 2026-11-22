from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Status(StrEnum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class Currency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class Base(DeclarativeBase):
    pass


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_amount"),
        CheckConstraint("currency IN ('RUB','USD','EUR')", name="ck_payment_currency"),
        CheckConstraint("status IN ('pending','succeeded','failed')", name="ck_payment_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str]
    extra_data: Mapped[dict] = mapped_column("metadata", JSONB)
    webhook_url: Mapped[str]
    status: Mapped[str] = mapped_column(String(16), server_default=Status.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    webhook_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Outbox(Base):
    __tablename__ = "outbox"

    payment_id: Mapped[UUID] = mapped_column(ForeignKey("payments.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("ix_outbox_pending", Outbox.created_at, postgresql_where=Outbox.published_at.is_(None))
