import asyncio
import json
import os
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import aio_pika
import httpx
import pytest
from sqlalchemy import event, select, text

from app import processing
from app.api import app
from app.db import engine, sessions
from app.models import Outbox, Payment, Status

API = "http://api:8000/api/v1/payments"
RECEIVER = "http://webhook:8080"


def request_body(behavior="ok"):
    return {
        "amount": "1250.50", "currency": "RUB", "description": "Книга",
        "metadata": {"order_id": 42}, "webhook_url": f"{RECEIVER}/{behavior}",
    }


@pytest.fixture
async def client():
    async with httpx.AsyncClient(headers={"X-API-Key": os.environ["API_KEY"]}) as http:
        yield http
    await engine.dispose()


async def wait_for_delivery(http, payment_id):
    async with asyncio.timeout(45):
        while True:
            response = await http.get(f"{API}/{payment_id}")
            response.raise_for_status()
            if response.json()["webhook_delivered_at"]:
                return response.json()
            await asyncio.sleep(0.15)


async def test_contract(client):
    payload = request_body()
    url = f"{API}/{uuid4()}"
    async with httpx.AsyncClient() as anonymous:
        assert (await anonymous.post(API, json=payload)).status_code == 401
        assert (await anonymous.get(url)).status_code == 401
    assert (await client.get(url)).status_code == 404
    assert (await client.post(API, json=payload)).status_code == 422
    for invalid in ({"amount": "0.001"}, {"amount": "-1"}, {"currency": "GBP"}, {"webhook_url": "file:///tmp/x"}):
        response = await client.post(API, headers={"Idempotency-Key": str(uuid4())}, json=payload | invalid)
        assert response.status_code == 422


async def test_concurrent_replays_and_recovery(client, monkeypatch):
    headers = {"Idempotency-Key": str(uuid4())}
    payload = request_body("flaky")
    responses = await asyncio.gather(*(client.post(API, headers=headers, json=payload) for _ in range(8)))
    assert {r.status_code for r in responses} == {202}
    assert len({r.json()["payment_id"] for r in responses}) == 1
    assert len({r.json()["created_at"] for r in responses}) == 1
    payment_id = responses[0].json()["payment_id"]
    conflict = await client.post(API, headers=headers, json=payload | {"amount": "10.00"})
    assert conflict.status_code == 409

    result = await wait_for_delivery(client, payment_id)
    assert result["status"] in {"succeeded", "failed"}
    assert result["amount"] == "1250.50"
    assert result["metadata"] == payload["metadata"]
    events = (await client.get(f"{RECEIVER}/events/{payment_id}")).json()
    assert len(events) == 2
    assert events[0]["body"] == events[1]["body"]
    assert events[1]["body"]["status"] == result["status"]
    assert all(event["key"] == payment_id for event in events)
    assert events[1]["at"] - events[0]["at"] >= 0.95

    async with engine.connect() as db:
        published = await db.scalar(text("SELECT published_at FROM outbox WHERE payment_id=:id"), {"id": payment_id})
        assert published is not None

    gateway = AsyncMock()
    monkeypatch.setattr(processing, "simulate_gateway", gateway)
    await processing.process_payment(UUID(payment_id), client)
    gateway.assert_not_awaited()
    assert len((await client.get(f"{RECEIVER}/events/{payment_id}")).json()) == 2


async def test_third_failure_goes_to_dlq(client):
    response = await client.post(API, headers={"Idempotency-Key": str(uuid4())}, json=request_body("fail"))
    assert response.status_code == 202
    payment_id = response.json()["payment_id"]
    async with await aio_pika.connect(os.environ["RABBITMQ_URL"]) as conn:
        channel = await conn.channel()
        dlq = await channel.get_queue("payments.dlq")
        async with asyncio.timeout(50):
            async with dlq.iterator() as messages:
                async for message in messages:
                    if json.loads(message.body)["payment_id"] == payment_id:
                        await message.ack()
                        break
    result = (await client.get(f"{API}/{payment_id}")).json()
    assert result["status"] in {"succeeded", "failed"}
    assert result["processed_at"] and result["webhook_delivered_at"] is None
    events = (await client.get(f"{RECEIVER}/events/{payment_id}")).json()
    assert len(events) == 3
    assert events[0]["body"] == events[1]["body"] == events[2]["body"]
    assert events[2]["at"] - events[1]["at"] >= 1.95


async def test_outbox_insert_failure_rolls_back_payment(client):
    key = str(uuid4())

    def fail_insert(mapper, connection, target):
        raise RuntimeError("Injected outbox write failure")

    event.listen(Outbox, "before_insert", fail_insert)
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport) as local:
            response = await local.post(
                API, headers={"X-API-Key": os.environ["API_KEY"], "Idempotency-Key": key},
                json=request_body(),
            )
        assert response.status_code == 500
    finally:
        event.remove(Outbox, "before_insert", fail_insert)
    async with sessions() as db:
        assert await db.scalar(select(Payment.id).where(Payment.idempotency_key == key)) is None
    retry = await client.post(API, headers={"Idempotency-Key": key}, json=request_body())
    assert retry.status_code == 202


@pytest.mark.parametrize(("draw", "expected"), [(0.89, Status.succeeded), (0.9, Status.failed)])
async def test_gateway_outcomes(monkeypatch, draw, expected):
    delay = AsyncMock()
    monkeypatch.setattr(processing.asyncio, "sleep", delay)
    monkeypatch.setattr(processing.random, "random", lambda: draw)
    assert await processing.simulate_gateway() == expected
    delay.assert_awaited_once()
    assert 2 <= delay.await_args.args[0] <= 5
