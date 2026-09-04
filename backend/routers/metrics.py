# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.auth.authz import require_owner
from backend.db.engine import get_db
from backend.operations.metrics import collect_metrics, history
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/history", response_model=ResponseModel)
async def metrics_history(hours: int = 24, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    return ResponseModel(success=True, msg="Metrics history", data=history(db, hours=hours))


@router.post("/collect", response_model=ResponseModel)
async def collect_now(user: dict = Depends(require_owner)):
    await collect_metrics()
    return ResponseModel(success=True, msg="Metrics snapshot collected")


async def sse_generator(db: Session):
    """Yield the latest metrics snapshot every 5 seconds as SSE."""
    try:
        while True:
            data = history(db, hours=1)  # last hour gives fine granularity
            traffic = data.get("traffic", [])
            if traffic:
                latest = traffic[-1]
                yield f"data: {json.dumps(latest)}\n\n"
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        return


@router.get("/stream")
async def metrics_stream(request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """Server-Sent Events stream of live metrics.
    Emits a new data point every 5 seconds.
    """
    return StreamingResponse(
        sse_generator(db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
