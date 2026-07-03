import asyncio
from collections import Counter

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.db import crud
from backend.db.engine import get_db
from backend.node.requests import NodeRequests
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/security", tags=["Security"])


@router.get("/summary", response_model=ResponseModel)
async def security_summary(hours: int = 8, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    nodes = crud.get_all_nodes(db)
    users = crud.get_all_users(db)
    full_users = [u.name for u in users if (u.max_logins or 0) > 0]

    async def node_diag(node):
        req = NodeRequests(node.address, node.port, node.key)
        data = await run_in_threadpool(req.get_sessions, None, hours)
        return node.name, data or {}

    results = await asyncio.gather(*[node_diag(n) for n in nodes], return_exceptions=True)
    auth_errors = 0
    rejects = 0
    stale = 0
    per_node = []
    last_errors = []
    for item in results:
        if isinstance(item, Exception):
            continue
        node_name, data = item
        auth_errors += int(data.get("auth_errors") or 0)
        rejects += int(data.get("rejects") or 0)
        stale += int(data.get("stale_marker_count") or 0)
        le = data.get("last_error")
        if isinstance(le, dict):
            last_errors.extend([{"common_name": k, "line": v} for k, v in le.items()])
        elif le:
            last_errors.append({"common_name": "", "line": le})
        per_node.append({
            "node": node_name,
            "auth_errors": int(data.get("auth_errors") or 0),
            "rejects": int(data.get("rejects") or 0),
            "stale_markers": int(data.get("stale_marker_count") or 0),
            "live": int(data.get("live_count") or 0),
        })

    top = Counter()
    for e in last_errors:
        if e.get("common_name"):
            top[e["common_name"]] += 1

    return ResponseModel(success=True, msg="Security summary", data={
        "hours": hours,
        "auth_errors": auth_errors,
        "rejects": rejects,
        "stale_markers": stale,
        "per_node": per_node,
        "last_errors": last_errors[-50:],
        "top_common_names": top.most_common(20),
    })
