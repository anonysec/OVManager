"""Node CRUD operations — add/update/delete nodes and users.

Handles all direct interactions with OVNode instances for user management:
creating, activating/deactivating, deleting users, and downloading configs.
"""

import asyncio
import io
import time
import zipfile
from zipfile import ZIP_DEFLATED

from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.db import crud
from backend.logger import logger
from backend.node.requests import NodeRequests
from backend.operations.geolocation import geolocate
from backend.schema._input import NodeCreate


async def add_node_handler(request: NodeCreate, db: Session) -> bool:
    """Add a new node: validate connectivity, geolocate, persist to DB."""
    geo = geolocate(request.address)

    nr = NodeRequests(
        address=request.address,
        port=request.port,
        api_key=request.key,
        tunnel_address=request.tunnel_address or "",
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
        set_new_setting=request.set_new_setting,
        use_tls=request.use_tls,
    )

    ok = await run_in_threadpool(nr.check_node)
    if not ok:
        return False

    if request.set_new_setting:
        configured = await run_in_threadpool(
            nr.update_config,
            tunnel_address=request.tunnel_address or "",
            protocol=request.protocol,
            ovpn_port=request.ovpn_port,
            set_new_setting=True,
        )
        if not configured:
            logger.error("Node %s accepted health check but rejected configuration", request.address)
            return False

    crud.create_node(db, request, geo)
    return True


async def update_node_handler(node_id: int, request: NodeCreate, db: Session) -> tuple[bool, str]:
    """Update an existing node's configuration.

    DB changes are persisted first so metadata edits (rename, address/port
    change, status toggle) always succeed even when the node is offline —
    e.g. when moving a node to a new IP the old address may be unreachable.

    The live node sync (health check + optional config push) is best-effort:
    failures are logged and surfaced in the message, but they do not roll back
    the saved record.
    """
    existing = crud.get_node_by_id(db, node_id)
    if not existing:
        return False, "Node not found"

    geo = geolocate(request.address)
    api_key = request.key or existing.key

    # Persist first — this is the source of truth for the panel.
    crud.update_node(db, node_id, request, geo)

    # Metadata-only edits (rename, address/port change, status toggle) never
    # need to reach the node, so they return instantly even when the node is
    # offline. Only when the operator asks to apply VPN settings on the node
    # do we contact it — and even then a failure only downgrades the message.
    if not request.set_new_setting:
        return True, "Node updated successfully"

    nr = NodeRequests(
        address=request.address,
        port=request.port,
        api_key=api_key,
        tunnel_address=request.tunnel_address or "",
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
        set_new_setting=True,
        use_tls=request.use_tls,
    )

    ok = await run_in_threadpool(nr.check_node)
    if not ok:
        logger.warning(
            "Node %s updated in DB but unreachable for live sync", request.address
        )
        return True, "Node updated. Live node is unreachable — changes will apply on next reconnect."

    configured = await run_in_threadpool(
        nr.update_config,
        tunnel_address=request.tunnel_address or "",
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
        set_new_setting=True,
    )
    if not configured:
        logger.error("Node %s rejected configuration update", request.address)
        return True, "Node updated, but the new VPN settings could not be applied on the node."

    return True, "Node updated successfully"


async def delete_node_handler(node_id: int, db: Session) -> bool:
    """Delete a node from the panel."""
    crud.delete_node(db, node_id)
    return True


async def list_nodes_handler(db: Session) -> list:
    """List all nodes with their current status."""
    nodes = crud.get_all_nodes(db)
    result = []
    for n in nodes:
        result.append({
            "id": n.id,
            "name": n.name,
            "address": n.address,
            "tunnel_address": n.tunnel_address,
            "protocol": n.protocol,
            "ovpn_port": n.ovpn_port,
            "port": n.port,
            "status": n.status,
            "use_tls": n.use_tls,
            "country_code": n.country_code,
            "latitude": n.latitude,
            "longitude": n.longitude,
        })
    return result


async def get_node_status_handler(node_id: int, db: Session):
    """Get detailed status of a specific node."""
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return None

    nr = NodeRequests(
        address=node.address,
        port=node.port,
        api_key=node.key,
        use_tls=node.use_tls,
    )

    started = time.perf_counter()
    info, sessions = await asyncio.gather(
        run_in_threadpool(nr.get_node_info),
        run_in_threadpool(nr.get_sessions, None, 8),
    )
    info = info if isinstance(info, dict) else {}
    sessions = sessions if isinstance(sessions, dict) else {}

    return {
        "node": {
            "id": node.id,
            "name": node.name,
            "address": node.address,
            "status": node.status,
        },
        "node_info": info,
        "session_diagnostics": sessions,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "reachable": bool(info),
    }


async def create_user_on_all_nodes(name: str, db: Session, max_logins: int = 1, user_id: int = None):
    """Create a user on every active node concurrently.

    Uses numeric user ID as the OpenVPN CN and node-side identity.
    """
    nodes = crud.get_active_nodes(db)
    uid = str(user_id) if user_id else None
    tasks = []
    for n in nodes:
        nr = NodeRequests(address=n.address, port=n.port, api_key=n.key, use_tls=n.use_tls)
        tasks.append(run_in_threadpool(nr.create_user, name, max_logins, uid))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results


async def change_user_status_on_all_nodes(
    user_id: int, name: str, status: bool, db: Session, max_logins: int = None
) -> bool:
    """Toggle user status on every active node. Uses numeric user ID."""
    nodes = crud.get_active_nodes(db)
    uid = str(user_id)
    tasks = []
    for n in nodes:
        nr = NodeRequests(address=n.address, port=n.port, api_key=n.key, use_tls=n.use_tls)
        tasks.append(run_in_threadpool(nr.change_user_status, name, status, max_logins, uid))
    if not tasks:
        return True
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return all(result is True for result in results)


async def set_user_limit_on_all_nodes(name: str, max_logins: int, db: Session, user_id: int = None) -> bool:
    """Push max_login limit to every active node. Uses numeric user ID."""
    nodes = crud.get_active_nodes(db)
    uid = str(user_id) if user_id else name
    tasks = []
    for n in nodes:
        nr = NodeRequests(address=n.address, port=n.port, api_key=n.key, use_tls=n.use_tls)
        tasks.append(run_in_threadpool(nr.set_user_limit, uid, int(max_logins or 0)))
    if not tasks:
        return True
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return all(result is True for result in results)


async def download_ovpn_client_from_node(user_id: int, node_id: int, db: Session):
    """Download a user's .ovpn config from a specific node. Uses numeric user ID."""
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return None

    nr = NodeRequests(
        address=node.address,
        port=node.port,
        api_key=node.key,
        tunnel_address=node.tunnel_address or "",
        protocol=node.protocol,
        ovpn_port=node.ovpn_port,
        use_tls=node.use_tls,
    )
    return await run_in_threadpool(nr.download_ovpn_client, str(user_id))


async def download_all_ovpn_clients_from_node(node_id: int, db: Session) -> StreamingResponse | None:
    """Download all users' .ovpn configs from a node as a ZIP file. Uses numeric user IDs."""
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return None

    users = crud.get_all_users(db)
    nr = NodeRequests(
        address=node.address, port=node.port, api_key=node.key,
        tunnel_address=node.tunnel_address or "",
        protocol=node.protocol, ovpn_port=node.ovpn_port,
        use_tls=node.use_tls,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        for user in users:
            # Use download_ovpn_bytes() which returns raw bytes — avoids
            # depending on the internal .body attribute of starlette Response.
            content = await run_in_threadpool(nr.download_ovpn_bytes, str(user.id))
            if content:
                zf.writestr(f"{user.name}.ovpn", content)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{node.name}_all_clients.zip"'},
    )


async def delete_user_on_all_nodes(name: str, user_id: int, db: Session) -> bool:
    """Delete a user from every active node. Uses numeric user ID."""
    nodes = crud.get_active_nodes(db)
    if not nodes:
        return True
    tasks = []
    for n in nodes:
        nr = NodeRequests(address=n.address, port=n.port, api_key=n.key, use_tls=n.use_tls)
        tasks.append(run_in_threadpool(nr.delete_user, str(user_id)))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Every active node must acknowledge the deletion. A partial success must
    # remain visible so the Manager does not remove its source-of-truth row
    # while a client certificate survives on another node.
    return bool(results) and all(r is True for r in results)
