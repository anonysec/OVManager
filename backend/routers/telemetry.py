"""Telemetry routers: activity feed, metrics, notifications, live SSE stream.

Four single-endpoint routers live here instead of four files: each is one
APIRouter with its own prefix/tags, so routes are unchanged — only the
file count is smaller.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from backend.auth.auth import get_current_user
from backend.auth.authz import require_owner
from backend.db import crud
from backend.db.engine import get_db
from backend.operations.audit import recent_events
from backend.operations.live import bus
from backend.operations.metrics import collect_metrics, history
from backend.schema import ResponseModel

activity_router = APIRouter(prefix="/activity", tags=["Activity"])


@activity_router.get("/", response_model=ResponseModel)
async def get_activity(
    limit: int = 100,
    action: str | None = None,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    actor = None if user.get("type") == "owner" else user.get("username")
    return ResponseModel(success=True, msg="Activity retrieved", data=recent_events(db, limit=limit, actor=actor, action=action))


metrics_router = APIRouter(prefix="/metrics", tags=["Metrics"])


@metrics_router.get("/history", response_model=ResponseModel)
async def metrics_history(hours: int = 24, db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    return ResponseModel(success=True, msg="Metrics history", data=history(db, hours=hours))


@metrics_router.post("/collect", response_model=ResponseModel)
async def collect_now(user: dict = Depends(require_owner)):
    await collect_metrics()
    return ResponseModel(success=True, msg="Metrics snapshot collected")


notifications_router = APIRouter(prefix="/notifications", tags=["Notifications"])


@notifications_router.get("/", response_model=ResponseModel)
async def notifications(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    nodes = crud.get_all_nodes(db)
    items = []
    for n in nodes:
        if not n.status:
            items.append({"level": "danger", "type": "node_offline", "title": f"Node {n.name} is offline", "target": n.name})
    return ResponseModel(success=True, msg="Notifications", data=items[:100])


live_router = APIRouter(prefix="/live", tags=["Live"])

_HEARTBEAT_SECONDS = 15


def _format_event(topic: str, data: dict) -> str:
    return f"event: {topic}\ndata: {json.dumps(data, default=str)}\n\n"


@live_router.get("/stream", include_in_schema=False)
async def live_stream(user: dict = Depends(get_current_user)):
    """Authenticated Server-Sent Events stream for live UI updates.

    The stream carries lightweight invalidation events only ("users",
    "usage", "nodes"); the frontend reacts by refetching the affected data
    through the normal REST endpoints. No sensitive payloads travel over the
    stream itself, and every event — not just heartbeats — re-asserts
    liveness of the channel.

    Transport notes:
    - GET + Bearer auth, so it passes the CSRF and URLPath middleware unchanged.
    - ``X-Accel-Buffering: no`` tells nginx/caddy to flush each event instead of
      buffering the whole response (a common "SSE doesn't arrive" gotcha).
    - A comment heartbeat (``: hb``) every 15s keeps idle connections alive
      through proxies with short timeouts.
    """
    q = bus.subscribe()

    async def generate():
        try:
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
