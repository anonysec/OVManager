# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

import inspect
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.auth.authz import require_owner
from backend.db import crud
from backend.db.engine import get_db
from backend.node.requests import node_client
from backend.node.task import (
    add_node_handler,
    delete_node_handler,
    download_all_ovpn_clients_from_node,
    download_ovpn_client_from_node,
    get_node_status_handler,
    list_nodes_handler,
    update_node_handler,
)
from backend.operations import live
from backend.operations.audit import log_event
from backend.schema import NodeCreate, ResponseModel

router = APIRouter(prefix="/nodes", tags=["Nodes"])


class NodeDnsUpdate(BaseModel):
    """Per-node DNS servers. Omitted fields keep the node's current value."""

    dns1: str | None = None
    dns2: str | None = None


class NodeIpv6Update(BaseModel):
    """Per-node IPv6 setting. Omitted fields keep the node's current value."""

    enable_ipv6: bool | None = None
    ipv6_prefix: str | None = None


class NodePortsUpdate(BaseModel):
    """Per-node extra VPN ports. An empty string clears them."""

    extra_ports: str | None = None


def _supports_return_envelope(method) -> bool:
    """True when update_config() declares the ``return_envelope`` opt-in.

    Test doubles expose ``**kwargs`` (or an older signature); only pass the
    opt-in to callables that spell it out, so route tests keep working.
    """
    try:
        return "return_envelope" in inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False


@router.post("/", response_model=ResponseModel)
async def add_node(
    request: NodeCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):

    # Names must stay unique: they key per-user traffic baselines and appear
    # in subscription output, so two "eu-1" nodes would cross-bill and be
    # indistinguishable.
    if crud.get_node_by_name(db, request.name) is not None:
        return ResponseModel(
            success=False,
            msg=f"A node named '{request.name}' already exists. Choose a different name.",
        )

    new_node = await add_node_handler(request, db)
    if new_node:
        live.publish("nodes", {"op": "add"})
        log_event(db, "node.create", actor=user.get("username"), target=request.name)
    return ResponseModel(
        success=new_node,
        msg="Node added successfully"
        if new_node
        else "Failed to add node — the panel could not reach it. "
        "Check address, port, API key and the TLS switch, or use Test connection first.",
    )


@router.post("/test", response_model=ResponseModel)
async def test_node(
    request: NodeCreate,
    user: dict = Depends(require_owner),
):
    """Check connectivity to a node without saving it.

    Read-only: builds a one-off client from the payload and hits
    /sync/status. Lets the Add Node form validate before persisting.
    """
    from fastapi.concurrency import run_in_threadpool

    from backend.node.requests import NodeRequests

    if not (request.key or "").strip():
        return ResponseModel(success=False, msg="API key is required.")
    try:
        nr = NodeRequests(
            address=request.address,
            port=request.port,
            api_key=request.key,
            use_tls=request.use_tls,
        )
    except ValueError as e:
        return ResponseModel(success=False, msg=f"Invalid address: {e}")
    ok = await run_in_threadpool(nr.check_node)
    if ok:
        return ResponseModel(success=True, msg="Node is reachable.", data={"reachable": True})
    return ResponseModel(
        success=False,
        msg="Node unreachable — check address (public IP, not 10.x/192.168.x unless shared LAN), "
        "service port (2083, not the 1194 VPN port), exact API key, and that the TLS switch "
        "matches the node (on for self-signed/LE, off only for None).",
    )


@router.put("/{node_id}", response_model=ResponseModel)
async def update_node(
    node_id: int,
    request: NodeCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):

    # Renaming onto another node's name would merge their traffic baselines.
    clash = crud.get_node_by_name(db, request.name)
    if clash is not None and clash.id != node_id:
        return ResponseModel(success=False, msg=f"Another node is already named '{request.name}'.")

    success, msg = await update_node_handler(node_id, request, db)
    if success:
        live.publish("nodes", {"op": "update"})
        log_event(db, "node.update", actor=user.get("username"), target=request.name)
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


@router.get("/{node_id}/logs", response_model=ResponseModel)
async def get_node_logs(
    node_id: int,
    level: str = "WARNING",
    limit: int = 100,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Proxy the node's in-memory log ring (NodeDrawer Logs tab)."""
    node = crud.get_node_by_id(db, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    req = node_client(node)
    data = await run_in_threadpool(req.get_logs, level, limit)
    return ResponseModel(success=True, msg="Node logs retrieved successfully", data=data)


@router.put("/{node_id}/dns", response_model=ResponseModel)
async def set_node_dns(
    node_id: int,
    request: NodeDnsUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Set per-node DNS servers pushed to VPN clients (owner-only).

    The node validates the addresses and rewrites its existing
    ``push "dhcp-option DNS ..."`` lines in place; omitted fields are left
    unchanged on the node.
    """
    node = crud.get_node_by_id(db, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if request.dns1 is None and request.dns2 is None:
        return ResponseModel(success=False, msg="Provide dns1 and/or dns2.")
    req = node_client(node)
    applied = await run_in_threadpool(
        req.update_config,
        tunnel_address=node.tunnel_address or "",
        protocol=node.protocol,
        ovpn_port=node.ovpn_port,
        set_new_setting=True,
        dns1=request.dns1,
        dns2=request.dns2,
    )
    if not applied:
        return ResponseModel(
            success=False,
            msg="The node rejected the DNS update — check the addresses are valid IPs and that the node is reachable.",
        )
    return ResponseModel(
        success=True,
        msg="DNS settings applied on the node.",
        data={"dns1": request.dns1, "dns2": request.dns2},
    )


@router.put("/{node_id}/ipv6", response_model=ResponseModel)
async def set_node_ipv6(
    node_id: int,
    request: NodeIpv6Update,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Enable/disable the VPN's IPv6 pool on a node (owner-only).

    The node validates the prefix, rewrites the generated IPv6 directives in
    server.conf and reloads OpenVPN (SIGHUP — no client teardown); omitted
    fields are left unchanged on the node.
    """
    node = crud.get_node_by_id(db, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if request.enable_ipv6 is None and request.ipv6_prefix is None:
        return ResponseModel(success=False, msg="Provide enable_ipv6 and/or ipv6_prefix.")
    req = node_client(node)
    applied = await run_in_threadpool(
        req.update_config,
        tunnel_address=node.tunnel_address or "",
        protocol=node.protocol,
        ovpn_port=node.ovpn_port,
        set_new_setting=True,
        enable_ipv6=request.enable_ipv6,
        ipv6_prefix=request.ipv6_prefix,
    )
    if not applied:
        return ResponseModel(
            success=False,
            msg="The node rejected the IPv6 update — check the prefix is a valid IPv6 network and that the node is reachable.",
        )
    return ResponseModel(
        success=True,
        msg="IPv6 settings applied on the node.",
        data={"enable_ipv6": request.enable_ipv6, "ipv6_prefix": request.ipv6_prefix},
    )


@router.put("/{node_id}/ports", response_model=ResponseModel)
async def set_node_ports(
    node_id: int,
    request: NodePortsUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Set the extra VPN ports clients reach the node on (owner-only).

    The node validates the comma-separated list (1-65535, distinct from the
    primary port), rebuilds its client template ``remote`` block and, on
    native installs, re-applies its NAT redirect rules. An empty string
    clears the extras. The node's own message is surfaced when available.
    """
    node = crud.get_node_by_id(db, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if request.extra_ports is None:
        return ResponseModel(
            success=False,
            msg="Provide extra_ports — a comma-separated port list, or an empty string to clear.",
        )
    req = node_client(node)
    kwargs = {
        "tunnel_address": node.tunnel_address or "",
        "protocol": node.protocol,
        "ovpn_port": node.ovpn_port,
        "set_new_setting": True,
        "extra_ports": request.extra_ports,
    }
    if _supports_return_envelope(req.update_config):
        kwargs["return_envelope"] = True
    answer = await run_in_threadpool(req.update_config, **kwargs)
    if answer is None:
        return ResponseModel(success=False, msg="Node unreachable — the ports were not changed.")
    if isinstance(answer, dict):
        success = bool(answer.get("success"))
        fallback = "Extra VPN ports applied on the node." if success else "The node rejected the extra ports."
        msg = str(answer.get("msg") or fallback)
        data = answer.get("data")
    else:
        success = bool(answer)
        msg = (
            "Extra VPN ports applied on the node."
            if success
            else "The node rejected the extra ports — check the values are comma-separated "
            "ports (1-65535, distinct from the VPN port) and that the node is reachable."
        )
        data = None
    if not success:
        return ResponseModel(success=False, msg=msg, data=data)
    log_event(
        db,
        "node.ports",
        actor=user.get("username"),
        target=node.name or str(node_id),
        detail=f"extra_ports={request.extra_ports}",
    )
    return ResponseModel(
        success=True,
        msg=msg,
        data=data if data is not None else {"extra_ports": request.extra_ports},
    )


@router.post("/{node_id}/restart", response_model=ResponseModel)
async def restart_node_vpn(
    node_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Restart the node's OpenVPN service (owner-only).

    Returns the node's own result envelope: ``data.openvpn_running`` is the
    liveness check the node made after the restart attempt.
    """
    node = crud.get_node_by_id(db, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    req = node_client(node)
    answer = await run_in_threadpool(req.restart_vpn)
    if not answer:
        return ResponseModel(success=False, msg="Node unreachable — the restart was not requested.")
    success = bool(answer.get("success"))
    if success:
        log_event(
            db,
            "node.restart",
            actor=user.get("username"),
            target=node.name or str(node_id),
            detail="OpenVPN restart requested",
        )
    return ResponseModel(
        success=success,
        msg=answer.get("msg") or "Restart request processed.",
        data=answer.get("data"),
    )


@router.post("/{node_id}/renew-cert", response_model=ResponseModel)
async def renew_node_server_cert(
    node_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Renew the node's OpenVPN server certificate (owner-only).

    Uses the node's own easyrsa; OpenVPN restarts afterwards so clients pick
    up the new certificate. Meant for a certificate that is close to expiry.
    """
    node = crud.get_node_by_id(db, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    req = node_client(node)
    answer = await run_in_threadpool(req.renew_server_cert)
    if not answer:
        return ResponseModel(success=False, msg="Node unreachable — nothing was renewed.")
    success = bool(answer.get("success"))
    if success:
        log_event(
            db,
            "node.renew_cert",
            actor=user.get("username"),
            target=node.name or str(node_id),
            detail="Server certificate renewed",
        )
    return ResponseModel(
        success=success,
        msg=answer.get("msg") or ("Server certificate renewed" if success else "Renewal failed"),
        data=answer.get("data"),
    )


@router.post("/{node_id}/update", response_model=ResponseModel)
async def update_node_software(
    node_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Trigger the node's self-update (owner-only).

    The node launches its own installer update detached and answers
    immediately; Docker nodes refuse and tell the operator to update the
    container from the host.
    """
    node = crud.get_node_by_id(db, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    req = node_client(node)
    answer = await run_in_threadpool(req.trigger_update)
    if not answer:
        return ResponseModel(success=False, msg="Node unreachable — the update was not started.")
    return ResponseModel(
        success=bool(answer.get("success")),
        msg=answer.get("msg") or "Node update request processed.",
        data=answer.get("data"),
    )


@router.get("/", response_model=ResponseModel)
async def list_nodes(
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
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
    if result:
        live.publish("nodes", {"op": "delete"})
        log_event(db, "node.delete", actor=user.get("username"), target=str(node_id))
    return ResponseModel(
        success=result,
        msg="Node deleted successfully" if result else "Failed to delete node",
    )
