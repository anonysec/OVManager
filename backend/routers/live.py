# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Authenticated Server-Sent Events stream for live UI updates.

The stream carries lightweight invalidation events only ("users", "usage",
"nodes"); the frontend reacts by refetching the affected data through the
normal REST endpoints. No sensitive payloads travel over the stream itself,
and every event — not just heartbeats — re-asserts liveness of the channel.

Transport notes:
- GET + Bearer auth, so it passes the CSRF and URLPath middleware unchanged.
- ``X-Accel-Buffering: no`` tells nginx/caddy to flush each event instead of
  buffering the whole response (a common "SSE doesn't arrive" gotcha).
- A comment heartbeat (``: hb``) every 15s keeps idle connections alive
  through proxies with short timeouts.
"""

import asyncio
import json
import time

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from backend.auth.auth import get_current_user
from backend.operations.live import bus

router = APIRouter(prefix="/live", tags=["Live"])

_HEARTBEAT_SECONDS = 15


def _format_event(topic: str, data: dict) -> str:
    return f"event: {topic}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/stream", include_in_schema=False)
async def live_stream(user: dict = Depends(get_current_user)):
    q = bus.subscribe()

    async def generate():
        try:
            # Immediate ready frame so clients can distinguish "connected"
            # from "stuck behind a buffering proxy".
            yield _format_event("ready", {"ts": time.time()})
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_SECONDS)
                    yield _format_event(evt.topic, {**evt.data, "ts": evt.ts})
                except TimeoutError:
                    yield ": hb\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
