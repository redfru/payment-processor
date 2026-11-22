import asyncio
import logging
import os
from contextlib import suppress
from uuid import UUID

import httpx
from faststream import AckPolicy, FastStream
from faststream.rabbit import Channel, QueueType, RabbitBroker, RabbitMessage, RabbitQueue

from app.db import engine
from app.outbox import relay
from app.processing import process_payment

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
dead = RabbitQueue("payments.dlq", queue_type=QueueType.QUORUM)
work = RabbitQueue(
    "payments.new", queue_type=QueueType.QUORUM,
    arguments={
        "x-delivery-limit": MAX_ATTEMPTS - 1,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": dead.name,
        "x-dead-letter-strategy": "at-least-once",
        "x-overflow": "reject-publish",
    },
)


async def main() -> None:
    broker = RabbitBroker(
        os.environ["RABBITMQ_URL"],
        default_channel=Channel(prefetch_count=1, publisher_confirms=True, on_return_raises=True),
        graceful_timeout=15,
    )
    service = FastStream(broker)
    async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
        @broker.subscriber(work, ack_policy=AckPolicy.MANUAL, no_reply=True)
        async def consume(message: RabbitMessage) -> None:
            attempt = 1 + int(message.headers.get("x-delivery-count", 0))
            try:
                body = await message.decode()
                await process_payment(UUID(body["payment_id"]), client)
            except Exception:
                logger.exception("Event %s failed on attempt %d", message.message_id, attempt)
                if attempt >= MAX_ATTEMPTS:
                    await message.reject()
                else:
                    await asyncio.sleep(2 ** (attempt - 1))
                    await message.reject(requeue=True)
            else:
                await message.ack()

        @service.on_startup
        async def prepare_queues() -> None:
            await broker.connect()
            await broker.declare_queue(dead)
            await broker.declare_queue(work)

        relay_task: asyncio.Task | None = None

        @service.after_startup
        async def start_relay() -> None:
            nonlocal relay_task
            relay_task = asyncio.create_task(relay(broker, work))

        try:
            await service.run()
        finally:
            if relay_task is not None:
                relay_task.cancel()
                with suppress(asyncio.CancelledError):
                    await relay_task
            await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
