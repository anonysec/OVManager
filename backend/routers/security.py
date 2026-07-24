import asyncio
import re
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.db import crud
from backend.db.engine import get_db
from backend.node.requests import NodeRequests
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/security", tags=["Security"])
TEHRAN = ZoneInfo("Asia/Tehran")


def _parse_log_line(line: str, common_name: str = "") -> dict:
    """Convert raw ovpanel-mlogin line to a clean max-login error object."""
    cn = common_name
    m_cn = re.search(r"CN=([^\s]+)", line)
    if m_cn:
        cn = m_cn.group(1)
    action = "reject" if "REJECT" in line else ("check_failed" if "FAILED" in line else "event")
    if "GLOBAL_REJECT" in line:
        scope = "global"
    elif "LOCAL_REJECT" in line or " REJECT" in line:
        scope = "local"
    else:
        scope = "global" if "GLOBAL" in line else "local"
    limit = re.search(r"(?:limit|global_limit)=([^\s;]+)", line)
    active = re.search(r"(?:global_active|active_files)=([^\s;]+)", line)
    msg = re.search(r"msg=([^\n]+)$", line)
    # journal line format: Jul 03 06:20:02 host tag: ... (server timezone is UTC)
    tehran_time = None
    ts = 0.0
    m_time = re.match(r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})", line)
    if m_time:
        try:
            year = datetime.utcnow().year
            dt = datetime.strptime(f"{year} {m_time.group(1)} {m_time.group(2)} {m_time.group(3)}", "%Y %b %d %H:%M:%S")
            dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))
            ts = dt_utc.timestamp()
            tehran_time = dt_utc.astimezone(TEHRAN).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            tehran_time = None
            ts = 0.0
    username = cn.rsplit("-", 1)[0] if "-" in cn else cn
    return {
        "ts": ts,
        "time_tehran": tehran_time,
        "username": username,
        "common_name": cn,
        "scope": scope,
        "action": action,
        "active": active.group(1) if active else None,
        "limit": limit.group(1) if limit else None,
        "reason": (msg.group(1).strip() if msg else ("max login reached" if "REJECT" in line else "global check failed")),
        "line": line,
    }


@router.get("/summary", response_model=ResponseModel)
async def security_summary(hours: int = 8, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    nodes = crud.get_all_nodes(db)

    async def node_diag(node):
        req = NodeRequests(node.address, node.port, node.key, use_tls=node.use_tls)
        data = await run_in_threadpool(req.get_sessions, None, hours)
        return node.name, data or {}

    results = await asyncio.gather(*[node_diag(n) for n in nodes], return_exceptions=True)
    auth_errors = 0
    rejects = 0
    stale = 0
    per_node = []
    clean_errors = []
    for item in results:
        if isinstance(item, Exception):
            continue
        node_name, data = item
        auth_errors += int(data.get("auth_errors") or 0)
        rejects += int(data.get("rejects") or 0)
        stale += int(data.get("stale_marker_count") or 0)
        le = data.get("last_error")
        if isinstance(le, dict):
            clean_errors.extend([{**_parse_log_line(v, k), "node": node_name} for k, v in le.items()])
        elif le:
            clean_errors.append({**_parse_log_line(le), "node": node_name})
        per_node.append({
            "node": node_name,
            "auth_errors": int(data.get("auth_errors") or 0),
            "rejects": int(data.get("rejects") or 0),
            "stale_markers": int(data.get("stale_marker_count") or 0),
            "live": int(data.get("live_count") or 0),
        })

    clean_errors.sort(key=lambda e: float(e.get("ts") or 0), reverse=True)
    top = Counter(e["common_name"] for e in clean_errors if e.get("common_name"))
    return ResponseModel(success=True, msg="Security summary", data={
        "hours": hours,
        "timezone": "Asia/Tehran",
        "auth_errors": auth_errors,
        "rejects": rejects,
        "stale_markers": stale,
        "per_node": per_node,
        "last_errors": clean_errors[:50],
        "top_common_names": top.most_common(20),
    })
