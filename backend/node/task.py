import asyncio

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.responses import Response, StreamingResponse
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.logger import logger
from backend.schema._input import NodeCreate
from .requests import NodeRequests
from backend.db import crud
from backend.db.models import Node


def _base_username_for_node(client_name: str, node_name: str) -> str:
    suffix = f"-{node_name}"
    if client_name.endswith(suffix):
        return client_name[: -len(suffix)]
    return client_name.rsplit("-", 1)[0] if "-" in client_name else client_name


def _apply_node_usage_to_db(node: Node, usage: dict, db: Session) -> None:
    """Accumulate one node's current usage into users.used without resetting.

    Important for node deletion: before removing a node from the panel we snapshot
    its latest counters, but we never zero `used` and we leave `node_usage` in
    place. If the node is later re-added with the same name, the old baseline
    prevents double-counting; if it is gone forever, total used remains intact.
    """
    import json

    if not usage:
        return
    per_user_total = usage.get("users", {}) or {}
    per_user_sessions = usage.get("sessions", {}) or {}
    if not per_user_total:
        return

    all_users = {u.name: u for u in crud.get_all_users(db)}
    for client_name, total_bytes in per_user_total.items():
        clean_username = _base_username_for_node(client_name, node.name)
        user = all_users.get(clean_username)
        if not user:
            logger.warning("User not found while applying node usage: %s", clean_username)
            continue

        try:
            node_usage = json.loads(user.node_usage or "{}")
            if not isinstance(node_usage, dict):
                node_usage = {}
        except (ValueError, TypeError):
            node_usage = {}

        prev = node_usage.get(node.name)
        sessions = per_user_sessions.get(client_name)
        delta = 0
        if isinstance(sessions, dict) and isinstance(prev, dict):
            for skey, cur in sessions.items():
                cur = int(cur or 0)
                last = int(prev.get(skey, 0) or 0)
                delta += (cur - last) if cur >= last else cur
            new_state = {k: int(v) for k, v in sessions.items()}
        elif isinstance(sessions, dict):
            prev_int = int(prev or 0) if not isinstance(prev, dict) else 0
            cur_total = int(sum(int(v or 0) for v in sessions.values()))
            delta = cur_total - prev_int if cur_total >= prev_int else cur_total
            new_state = {k: int(v) for k, v in sessions.items()}
        else:
            prev_int = int(prev or 0) if not isinstance(prev, dict) else 0
            cur_total = int(total_bytes or 0)
            delta = cur_total - prev_int if cur_total >= prev_int else cur_total
            new_state = cur_total

        if delta < 0:
            delta = 0
        user.used = (user.used or 0) + delta
        node_usage[node.name] = new_state
        user.node_usage = json.dumps(node_usage)
        logger.info("[%s] delete-node snapshot node=%s total=%s delta=%s", clean_username, node.name, int(total_bytes or 0), delta)


async def add_node_handler(request: NodeCreate, db: Session) -> bool:
    """Validate and store a node.

    This should be quick: it only checks node reachability/settings once and does
    not create users. User creation on nodes is done lazily on first download (or
    when explicitly syncing), which avoids the UI hanging when many users exist.
    """
    existing = crud.get_node_by_name(db, request.name)
    if existing:
        logger.warning("Node name already exists: %s", request.name)
        return False

    node_req = NodeRequests(
        request.address,
        request.port,
        request.key,
        request.tunnel_address,
        request.protocol,
        request.ovpn_port,
        request.set_new_setting,
    )
    if await run_in_threadpool(node_req.check_node):
        crud.create_node(db, request)
        logger.info(f"Node added successfully: {request.address}:{request.port}")
        return True

    logger.warning(f"Failed to add node: {request.address}:{request.port}")
    return False

async def update_node_handler(node_id: int, request: NodeCreate, db: Session) -> bool:
    """Update a node and apply OpenVPN server settings on that node."""
    current = crud.get_node_by_id(db, node_id)
    if not current:
        return False

    api_key = request.key or current.key
    node_req = NodeRequests(
        address=request.address,
        port=request.port,
        api_key=api_key,
        tunnel_address=request.tunnel_address,
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
        set_new_setting=True,
    )

    # Validate/apply settings before saving. If the new address/key is wrong,
    # do not poison the database with unreachable node data.
    if not await run_in_threadpool(node_req.check_node):
        logger.warning("Failed to update node; new node settings are unreachable: %s:%s", request.address, request.port)
        return False

    crud.update_node(db, node_id, request)
    logger.info(f"Node updated: {request.address}:{request.port}")
    return True

async def delete_node_handler(node_id: int, db: Session) -> bool:
    """Delete a node without resetting any user's total usage.

    Before deletion we make one best-effort usage snapshot from that node. The
    accumulated `users.used` value is never decreased, and per-node baselines are
    intentionally kept in `users.node_usage` to avoid double-counting if a node is
    later re-added with the same name.
    """
    node = crud.get_node_by_id(db, node_id)
    if node:
        try:
            usage = await get_users_used_traffic(node, db)
            if usage:
                _apply_node_usage_to_db(node, usage, db)
                db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("Could not snapshot usage before deleting node %s: %s", node.name, e)

        crud.delete_node(db, node.id)
        logger.info(f"Node deleted successfully: {node.name}; user total usage preserved")
        return True
    logger.warning("Failed to delete node: node id %s not found", node_id)
    return False


async def list_nodes_handler(db: Session) -> list:
    """Retrieve all nodes"""
    nodes_list = []
    nodes = crud.get_all_nodes(db)
    for node in nodes:
        node_info = {
            "id": node.id,
            "name": node.name,
            "address": node.address,
            "tunnel-address": node.tunnel_address,
            "tunnel_address": node.tunnel_address,
            "ovpn_port": node.ovpn_port,
            "protocol": node.protocol,
            "port": node.port,
            "key": node.key,
            "status": bool(node.status),
        }
        nodes_list.append(node_info)
    return nodes_list


async def get_node_status_handler(node_id: int, db: Session):
    """Get the status of a node"""
    node = crud.get_node_by_id(db, node_id)
    if node:
        # get_node_info() uses blocking `requests`; run it in a threadpool so a
        # slow/unreachable node can't block the event loop (which would freeze
        # the whole panel and make the dashboard hang / show 0 active nodes).
        node_req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        node_status, session_diagnostics = await asyncio.gather(
            run_in_threadpool(node_req.get_node_info),
            run_in_threadpool(node_req.get_sessions, None, 8),
            return_exceptions=True,
        )
        if isinstance(node_status, Exception):
            logger.warning("node status failed for %s: %s", node.name, node_status)
            node_status = {}
        if isinstance(session_diagnostics, Exception) or session_diagnostics is False:
            logger.warning("node session diagnostics failed for %s: %s", node.name, session_diagnostics)
            session_diagnostics = {}
        return {
            "address": node.address,
            "port": node.port,
            "name": node.name,
            "status": "active" if node.status else "inactive",
            "node_info": node_status,
            "session_diagnostics": session_diagnostics or {},
        }
    return None


async def create_user_on_all_nodes(name: str, db: Session, max_logins: int = 1):
    """Create a user on all nodes (concurrently, off the event loop)."""
    nodes = crud.get_all_nodes(db)
    if not nodes:
        return

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        if req.check_node():
            req.create_user(f"{name}-{node.name}", max_logins=max_logins)
            logger.info(
                f"User '{name}-{node.name}' created on node {node.address}:{node.port}"
            )
        else:
            logger.warning(
                f"Failed to create user '{name}-{node.name}' on node {node.address}:{node.port}"
            )

    await asyncio.gather(
        *[run_in_threadpool(work, node) for node in nodes], return_exceptions=True
    )


async def change_user_status_on_all_nodes(
    uuid: str, name: str, status: bool, db: Session
):
    nodes = crud.get_all_nodes(db)
    crud.change_user_status(db, uuid, status)

    user = crud.get_user_by_uuid(db, uuid)
    max_logins = user.max_logins if user else 1

    if not nodes:
        return

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        if req.check_node():
            req.change_user_status(
                f"{name}-{node.name}", status, max_logins=max_logins
            )
            logger.info(
                f"User '{name}-{node.name}' changed status on node {node.address}:{node.port}"
            )
        else:
            logger.warning(
                f"Failed to change user status '{name}-{node.name}' on node {node.address}:{node.port}"
            )

    await asyncio.gather(
        *[run_in_threadpool(work, node) for node in nodes], return_exceptions=True
    )


async def set_user_limit_on_all_nodes(name: str, max_logins: int, db: Session):
    """Push the max simultaneous logins limit for a user to all nodes."""
    nodes = crud.get_all_nodes(db)
    if not nodes:
        return

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        if req.check_node():
            req.set_user_limit(f"{name}-{node.name}", max_logins)
            logger.info(
                f"User '{name}-{node.name}' login limit set to {max_logins} "
                f"on node {node.address}:{node.port}"
            )
        else:
            logger.warning(
                f"Failed to set login limit for '{name}-{node.name}' "
                f"on node {node.address}:{node.port}"
            )

    await asyncio.gather(
        *[run_in_threadpool(work, node) for node in nodes], return_exceptions=True
    )


async def download_ovpn_client_from_node(
    uuid: str, node_id: int, db: Session
) -> Response | None:
    """Download OVPN client from a node"""
    node = crud.get_node_by_id(db, node_id)
    user = crud.get_user_by_uuid(db, uuid)
    if not node or not user:
        return None
    node_request = NodeRequests(
        address=node.address, port=node.port, api_key=node.key
    )
    client_name = f"{user.name}-{node.name}"

    # Make sure the client exists before downloading. Creating users through
    # OpenVPN's bash installer can be slow, especially on the first request, so
    # keep it off the event loop and allow a longer download timeout below.
    try:
        await run_in_threadpool(
            node_request.create_user,
            client_name,
            user.max_logins if user.max_logins is not None else 1,
        )
        await run_in_threadpool(
            node_request.set_user_limit,
            client_name,
            user.max_logins if user.max_logins is not None else 1,
        )
    except Exception as e:
        logger.warning(f"Could not pre-create/sync user '{client_name}' before download: {e}")

    # Blocking HTTP -> threadpool. Use a longer timeout because a node may need
    # to generate the .ovpn file on-demand.
    result = await run_in_threadpool(
        node_request.download_ovpn_client,
        client_name,
        120,
    )
    if result:
        logger.info(
            f"OVPN client downloaded for user '{client_name}' on node {node.address}:{node.port}"
        )
        return result
    return None


async def download_all_ovpn_clients_from_node(node_id: int, db: Session) -> StreamingResponse | None:
    """Generate a ZIP containing every user's .ovpn config for one node."""
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return None

    users = crud.get_all_users(db)
    node_request = NodeRequests(address=node.address, port=node.port, api_key=node.key)
    zip_buffer = BytesIO()
    errors: list[str] = []

    def build_zip():
        with ZipFile(zip_buffer, "w", compression=ZIP_DEFLATED) as zf:
            for user in users:
                client_name = f"{user.name}-{node.name}"
                try:
                    # Ensure the config exists and has the current max-login limit.
                    node_request.create_user(
                        client_name,
                        user.max_logins if user.max_logins is not None else 1,
                    )
                    node_request.set_user_limit(
                        client_name,
                        user.max_logins if user.max_logins is not None else 1,
                    )
                    response = node_request.download_ovpn_client(client_name, timeout=120)
                    body = getattr(response, "body", None) if response else None
                    if not body:
                        errors.append(f"{client_name}: download failed")
                        continue
                    zf.writestr(f"{client_name}.ovpn", body)
                except Exception as e:
                    errors.append(f"{client_name}: {e}")
            if errors:
                zf.writestr("errors.txt", "\n".join(errors) + "\n")
        zip_buffer.seek(0)

    await run_in_threadpool(build_zip)
    filename = f"ovpn-configs-{node.name}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


async def delete_user_on_all_nodes(name: str, db: Session) -> bool:
    """Delete a user from all nodes (concurrently, off the event loop)."""
    nodes = crud.get_all_nodes(db)
    if not nodes:
        return False

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        if req.check_node():
            req.delete_user(f"{name}-{node.name}")
            logger.info(
                f"User '{name}-{node.name}' deleted on node {node.address}:{node.port}"
            )
        else:
            logger.warning(
                f"Failed to delete user '{name}-{node.name}' on node {node.address}:{node.port}"
            )

    await asyncio.gather(
        *[run_in_threadpool(work, node) for node in nodes], return_exceptions=True
    )
    return True


async def get_active_connection_counts(db: Session) -> dict[str, int]:
    """Return {panel_username: live_session_count} across all nodes."""
    nodes = crud.get_all_nodes(db)
    counts: dict[str, int] = {}

    def base_username(common_name: str, node_name: str) -> str:
        suffix = f"-{node_name}"
        if common_name.endswith(suffix):
            return common_name[: -len(suffix)]
        return common_name.rsplit("-", 1)[0] if "-" in common_name else common_name

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        data = req.get_sessions(hours=1)
        if not data:
            return {}
        local: dict[str, int] = {}
        for session in data.get("live_sessions") or []:
            common_name = session.get("common_name") or ""
            if not common_name:
                continue
            username = base_username(common_name, node.name)
            local[username] = local.get(username, 0) + 1
        return local

    raw = await asyncio.gather(
        *[run_in_threadpool(work, node) for node in nodes], return_exceptions=True
    )
    for item in raw:
        if isinstance(item, Exception):
            logger.warning("active connection count failed: %s", item)
            continue
        for username, count in item.items():
            counts[username] = counts.get(username, 0) + int(count or 0)
    return counts


async def get_user_session_diagnostics(name: str, db: Session, hours: int = 8) -> dict:
    """Collect live sessions/stale markers/auth rejects for one panel user."""
    nodes = crud.get_all_nodes(db)
    results = []

    def work(node):
        common_name = f"{name}-{node.name}"
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        data = req.get_sessions(common_name=common_name, hours=hours)
        if data is False:
            return {
                "node_id": node.id,
                "node_name": node.name,
                "common_name": common_name,
                "reachable": False,
            }
        return {
            "node_id": node.id,
            "node_name": node.name,
            "address": node.address,
            "port": node.port,
            "common_name": common_name,
            "reachable": True,
            **data,
        }

    raw = await asyncio.gather(
        *[run_in_threadpool(work, node) for node in nodes], return_exceptions=True
    )
    for item in raw:
        if isinstance(item, Exception):
            logger.warning("session diagnostics task failed: %s", item)
            continue
        results.append(item)

    totals = {
        "live_count": sum(int(r.get("live_count") or 0) for r in results),
        "stale_marker_count": sum(int(r.get("stale_marker_count") or 0) for r in results),
        "auth_errors": sum(int(r.get("auth_errors") or 0) for r in results),
        "rejects": sum(int(r.get("rejects") or 0) for r in results),
        "global_rejects": sum(int(r.get("global_rejects") or 0) for r in results),
    }
    return {"username": name, "hours": hours, "totals": totals, "nodes": results}


async def disconnect_user_on_all_nodes(name: str, db: Session) -> dict:
    """Best-effort per-user disconnect/cleanup on all nodes."""
    nodes = crud.get_all_nodes(db)
    results = []

    def work(node):
        common_name = f"{name}-{node.name}"
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        data = req.disconnect_user(common_name)
        if data is False:
            return {
                "node_id": node.id,
                "node_name": node.name,
                "common_name": common_name,
                "reachable": False,
                "success": False,
            }
        return {
            "node_id": node.id,
            "node_name": node.name,
            "common_name": common_name,
            "reachable": True,
            "success": True,
            **data,
        }

    raw = await asyncio.gather(
        *[run_in_threadpool(work, node) for node in nodes], return_exceptions=True
    )
    for item in raw:
        if isinstance(item, Exception):
            logger.warning("disconnect task failed: %s", item)
            continue
        results.append(item)
    return {"username": name, "nodes": results}


async def get_users_used_traffic(node: Node, db: Session) -> dict:
    """Get a node's usage: {"users": {cn: total}, "sessions": {cn: {key: bytes}}}.

    get_users_usage() uses blocking requests, so run it in a threadpool to keep
    the event loop free.
    """
    node_requests = NodeRequests(address=node.address, port=node.port, api_key=node.key)
    response = await run_in_threadpool(node_requests.get_users_usage)

    if not response:
        return {}
    return response
