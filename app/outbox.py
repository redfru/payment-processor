import asyncio
import logging
from datetime import UTC, datetime

from faststream.rabbit import RabbitBroker, RabbitQueue
from sqlalchemy import select

from app.db import sessions
from app.models import Outbox

logger = logging.getLogger(__name__)


async def publish_next(broker: RabbitBroker, queue: RabbitQueue) -> bool:
    async with sessions.begin() as db:
        event = await db.scalar(
            select(Outbox).where(Outbox.published_at.is_(None))
            .order_by(Outbox.created_at).limit(1).with_for_update(skip_locked=True)
        )
        if event is None:
            return False
        event_id = str(event.payment_id)
        await broker.publish(
            {"payment_id": event_id}, queue=queue, message_id=event_id,
            persist=True, mandatory=True, timeout=5,
        )
        event.published_at = datetime.now(UTC)
    return True


async def relay(broker: RabbitBroker, queue: RabbitQueue) -> None:
    while True:
        try:
            if not await publish_next(broker, queue):
                await asyncio.sleep(0.25)
        except Exception:
            logger.exception("Outbox publication failed; the event remains pending")
            await asyncio.sleep(2)
