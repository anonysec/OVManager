import asyncio
from datetime import date

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.config import config
from backend.db.engine import get_db
from backend.db import crud
from backend.node.task import download_ovpn_client_from_node
from backend.node.requests import NodeRequests


templates = Jinja2Templates(directory="frontend/templates")
router = APIRouter(prefix=f"/{config.SUBSCRIPTION_PATH}", tags=["Subscription"])


@router.get("/{uuid}")
async def get_subscription(
    request: Request,
    uuid: str,
    db: Session = Depends(get_db),
):
    user = crud.get_user_by_uuid(db, uuid)
    if not user:
        raise HTTPException(status_code=404)
    used = user.used or 0
    if not bool(user.is_active):
        raise HTTPException(status_code=403, detail="User is inactive")
    if user.expiry_date and user.expiry_date < date.today():
        raise HTTPException(status_code=403, detail="User is expired")
    if user.total is not None and used >= user.total:
        raise HTTPException(status_code=403, detail="Traffic limit reached")
    nodes = [n for n in crud.get_all_nodes(db) if n.status]
    ovpn_download_links = {}

    # check_node() is blocking (requests); run all nodes concurrently in a
    # threadpool so one slow/unreachable node can't block the event loop or
    # stall the whole subscription page.
    async def is_up(node):
        try:
            return await run_in_threadpool(
                NodeRequests(
                    address=node.address, port=node.port, api_key=node.key
                ).check_node
            )
        except Exception:
            return False

    results = await asyncio.gather(*[is_up(n) for n in nodes]) if nodes else []
    for node, up in zip(nodes, results):
        if not up:
            continue
        ovpn_download_links[node.name] = str(
            request.url_for("download_ovpn", uuid=uuid, node_name=node.name)
        )

    return templates.TemplateResponse(
        "subscription.html",
        {
            "request": request,
            "name": user.name,
            "expiry_date": user.expiry_date,
            "total": user.total,
            "used": user.used,
            "is_active": user.is_active,
            "ovpn_download_links": ovpn_download_links,
        },
    )


@router.get("/download/{uuid}/{node_name}")
async def download_ovpn(
    uuid: str,
    node_name: str,
    db: Session = Depends(get_db),
):
    user = crud.get_user_by_uuid(db, uuid)
    if not user:
        raise HTTPException(status_code=404)
    used = user.used or 0
    if not bool(user.is_active):
        raise HTTPException(status_code=403, detail="User is inactive")
    if user.expiry_date and user.expiry_date < date.today():
        raise HTTPException(status_code=403, detail="User is expired")
    if user.total is not None and used >= user.total:
        raise HTTPException(status_code=403, detail="Traffic limit reached")
    node_obj = crud.get_node_by_name(db, node_name)
    if not node_obj:
        raise HTTPException(status_code=404)
    response = await download_ovpn_client_from_node(user.uuid, node_obj.id, db)
    if not response:
        raise HTTPException(status_code=404, detail="File not found")
    return response
