from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue

from app.models import Currency, Status


class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    amount: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]
    currency: Currency
    description: Annotated[str, Field(max_length=2000)]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    webhook_url: HttpUrl


class PaymentAccepted(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: UUID = Field(validation_alias="id")
    status: Status
    created_at: datetime


class PaymentDetail(PaymentAccepted):
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, JsonValue] = Field(validation_alias="extra_data")
    webhook_url: str
    idempotency_key: str
    processed_at: datetime | None
    webhook_delivered_at: datetime | None
