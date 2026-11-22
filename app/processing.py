import asyncio
import random
from datetime import UTC, datetime
from uuid import UUID

import httpx

from app.db import sessions
from app.models import Payment, Status


async def simulate_gateway() -> Status:
    await asyncio.sleep(random.uniform(2, 5))
    return Status.succeeded if random.random() < 0.9 else Status.failed


async def process_payment(payment_id: UUID, client: httpx.AsyncClient) -> None:
    async with sessions.begin() as db:
        payment = await db.get_one(Payment, payment_id, with_for_update=True)
        if payment.status == Status.pending:
            payment.status = await simulate_gateway()
            payment.processed_at = datetime.now(UTC)

    async with sessions.begin() as db:
        payment = await db.get_one(Payment, payment_id, with_for_update=True)
        if payment.webhook_delivered_at is not None:
            return
        event = {
            "payment_id": str(payment.id),
            "status": payment.status,
            "amount": format(payment.amount, "f"),
            "currency": payment.currency,
            "processed_at": payment.processed_at.isoformat(),
            "metadata": payment.extra_data,
        }
        async with asyncio.timeout(8):
            async with client.stream(
                "POST", payment.webhook_url, json=event,
                headers={"Idempotency-Key": str(payment.id)},
            ) as response:
                response.raise_for_status()
        payment.webhook_delivered_at = datetime.now(UTC)
