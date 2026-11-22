import os
import secrets
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db import engine, sessions
from app.models import Outbox, Payment
from app.schemas import PaymentAccepted, PaymentDetail, PaymentRequest

api_key = os.environ["API_KEY"].encode()
if not api_key:
    raise ValueError("API_KEY must be nonempty")


async def authenticate(
    value: Annotated[str | None, Security(APIKeyHeader(name="X-API-Key", auto_error=False))],
) -> None:
    if not value or not secrets.compare_digest(value.encode(), api_key):
        raise HTTPException(401, "Invalid API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(dependencies=[Depends(authenticate)], openapi_url=None, lifespan=lifespan)


@app.post("/api/v1/payments", status_code=202, response_model=PaymentAccepted)
async def create_payment(
    body: PaymentRequest,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=255, pattern=r"^[!-~]+$")],
):
    fields = {
        "idempotency_key": idempotency_key,
        "amount": body.amount,
        "currency": body.currency,
        "description": body.description,
        "extra_data": body.metadata,
        "webhook_url": str(body.webhook_url),
    }
    async with sessions.begin() as db:
        statement = (
            insert(Payment)
            .values(id=uuid4(), **fields)
            .on_conflict_do_nothing(index_elements=[Payment.idempotency_key])
            .returning(Payment)
        )
        payment = (await db.scalars(statement)).one_or_none()
        if payment is not None:
            db.add(Outbox(payment_id=payment.id))
        else:
            payment = await db.scalar(select(Payment).filter_by(**fields))
            if payment is None:
                raise HTTPException(409, "Idempotency-Key already used for a different payment")
    return payment


@app.get("/api/v1/payments/{payment_id}", response_model=PaymentDetail)
async def get_payment(payment_id: UUID):
    async with sessions() as db:
        payment = await db.get(Payment, payment_id)
        if payment is None:
            raise HTTPException(404, "Payment not found")
        return payment
