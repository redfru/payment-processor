import logging
import time
from collections import defaultdict

from fastapi import FastAPI, Header, Response

app = FastAPI()
events = defaultdict(list)


@app.post("/{behavior}")
async def receive(behavior: str, event: dict, idempotency_key: str = Header()):
    history = events[event["payment_id"]]
    history.append({"body": event, "key": idempotency_key, "at": time.monotonic()})
    logging.getLogger("uvicorn.error").info("Webhook %s, attempt %d: %s", behavior, len(history), event)
    if behavior == "fail" or (behavior == "flaky" and len(history) == 1):
        return Response(status_code=503)
    return Response(status_code=204)


@app.get("/events/{payment_id}")
async def received(payment_id: str):
    return events.get(payment_id, [])
