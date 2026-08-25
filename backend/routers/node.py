# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.auth.authz import require_owner
from backend.db import crud
from backend.db.engine import get_db
from backend.node.task import (
    add_node_handler,
    delete_node_handler,
    download_all_ovpn_clients_from_node,
    download_ovpn_client_from_node,
    get_node_status_handler,
    list_nodes_handler,
    update_node_handler,
)
from backend.schema._input import NodeCreate
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/nodes", tags=["Nodes"])


@router.post("/", response_model=ResponseModel)
async def add_node(
    request: NodeCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):

    new_node = await add_node_handler(request, db)
    return ResponseModel(
        success=new_node,
        msg="Node added successfully" if new_node else "Failed to add node",
    )


@router.put("/{node_id}", response_model=ResponseModel)
async def update_node(
    node_id: int,
    request: NodeCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):

    success, msg = await update_node_handler(node_id, request, db)
    return ResponseModel(success=success, msg=msg)


@router.get("/{node_id}/status/", response_model=ResponseModel)
async def get_node_status(
    node_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):

    node_status = await get_node_status_handler(node_id, db)
    if node_status is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return ResponseModel(
        success=True,
        msg="Node status retrieved successfully",
        data=node_status,
    )


@router.get("/", response_model=ResponseModel)
async def list_nodes(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    nodes = await list_nodes_handler(db)
    return ResponseModel(
        success=True,
        msg="Nodes retrieved successfully",
        data=nodes,
    )


@router.get(
    "/ovpn/{uuid}/{node_id}",
    description="Download OVPN client configuration from a node",
)
async def download_ovpn_client(
    node_id: int,
    uuid: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    db_user = crud.get_user_by_uuid(db, uuid)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if user["type"] != "owner" and db_user.owner != user["username"]:
        raise HTTPException(status_code=403, detail="Not your user")
    from datetime import datetime

    today_utc = datetime.now(UTC).date()
    if not db_user.is_active or (db_user.expiry_date and db_user.expiry_date < today_utc):
        raise HTTPException(status_code=403, detail="User account is not active")
    if db_user.total is not None and (db_user.used or 0) >= db_user.total:
        raise HTTPException(status_code=403, detail="User traffic limit reached")
    response = await download_ovpn_client_from_node(user_id=db_user.id, node_id=node_id, db=db)
    if response:
        return response
    raise HTTPException(status_code=404, detail="OVPN file not found")


@router.get(
    "/ovpn-all/{node_id}",
    description="Download all OVPN client configurations from a node as a ZIP",
)
async def download_all_ovpn_clients(
    node_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    response = await download_all_ovpn_clients_from_node(node_id=node_id, db=db)
    if response:
        return response
    raise HTTPException(status_code=404, detail="Node not found or configs unavailable")


@router.delete("/{node_id}", response_model=ResponseModel)
async def delete_node(
    node_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):

    result = await delete_node_handler(node_id, db)
    return ResponseModel(
        success=result,
        msg="Node deleted successfully" if result else "Failed to delete node",
    )
