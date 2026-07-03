import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.db import crud
from backend.db.engine import get_db
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/", response_model=ResponseModel)
async def notifications(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    nodes = crud.get_all_nodes(db)
    users = crud.get_all_users(db)
    items = []
    for n in nodes:
        if not n.status:
            items.append({"level": "danger", "type": "node_offline", "title": f"Node {n.name} is offline", "target": n.name})
    for u in users:
        if not bool(u.is_active):
            items.append({"level": "warning", "type": "user_inactive", "title": f"User {u.name} is inactive", "target": u.name})
    return ResponseModel(success=True, msg="Notifications", data=items[:100])
