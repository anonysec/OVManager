"""Node CRUD operations — add/update/delete nodes and users.

Direct interactions with OVNode instances: creating, activating and
deactivating users, deleting them, and downloading configs.
"""

import asyncio
import re
import time
import zipfile
from tempfile import SpooledTemporaryFile
from zipfile import ZIP_DEFLATED

from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from backend.db import crud
from backend.logger import logger
from backend.node.fanout import run_bounded
from backend.node.requests import NodeRequests, node_client
from backend.schema import NodeCreate
from backend.utils.geolocation import geolocate
from backend.version import __version__ as PANEL_VERSION


def node_version_compat(agent_version: object) -> dict:
    """Judge a node agent version against this panel.

    Policy (documented in OVNode docs): same major release is compatible
    (minor drift tolerated — both sides ignore unknown keys); a newer node
    than the panel is unsupported (the panel may not understand it); a
    different major is incompatible. Unparseable/missing versions are
    unknown, never silently accepted as compatible.
    """

    def _parts(value: object) -> tuple[int, ...] | None:
        try:
            nums = str(value).strip().lstrip("v").split(".")
            return tuple(int(p) for p in nums[:3])
        except (ValueError, TypeError, AttributeError):
            return None

    agent = _parts(agent_version)
    panel = _parts(PANEL_VERSION)
    if not agent or not panel:
        return {"verdict": "unknown", "agent_version": agent_version, "panel_version": PANEL_VERSION}
    if agent[0] != panel[0]:
        verdict = "incompatible"
    elif agent > panel:
        verdict = "node-newer"
    else:
        verdict = "compatible"
    return {"verdict": verdict, "agent_version": agent_version, "panel_version": PANEL_VERSION}


async def _resolve_pinned_ca(request: NodeCreate) -> str | None:
    """Fetch the node's certificate before any keyed request is sent.

    Trust-on-first-use is only worth anything if it happens first: the API key
    is the credential for every later call, so sending it over an unpinned
    connection hands it to whoever answered. Returns None for a failed fetch
    (the caller then proceeds without a pin, as before).
    """
    return await _pin_node_certificate(request.address, request.port)


async def add_node_handler(request: NodeCreate, db: Session) -> bool:
    geo = await run_in_threadpool(geolocate, request.address)

    server_ca = request.cert or await _resolve_pinned_ca(request)

    nr = NodeRequests(
        address=request.address,
        port=request.port,
        api_key=request.key,
        tunnel_address=request.tunnel_address or "",
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
        server_ca=server_ca,
    )

    ok = await run_in_threadpool(nr.check_node)
    if not ok:
        return False

    configured = await run_in_threadpool(
        nr.update_config,
        tunnel_address=request.tunnel_address or "",
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
    )
    if not configured:
        logger.error("Node %s accepted health check but rejected configuration", request.address)
        return False

    node = crud.create_node(db, request, geo)

    if server_ca and getattr(node, "server_ca", None) != server_ca:
        node.server_ca = server_ca
        db.commit()

    return True


async def _pin_node_certificate(address: str, port: int) -> str | None:
    """Fetch the node's TLS cert (TOFU) for storage on the node row.

    The address may be a bare IP/hostname or carry a scheme; the cert fetch
    uses the host:port pair only.
    """
    from urllib.parse import urlsplit

    raw = str(address or "").strip()
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname or raw
    try:
        port = int(parsed.port or port)
    except (TypeError, ValueError):
        return None

    from backend.node.pki import fetch_server_cert

    return await run_in_threadpool(fetch_server_cert, host, port)


async def update_node_handler(node_id: int, request: NodeCreate, db: Session) -> tuple[bool, str]:
    """Update an existing node's configuration.

    DB changes are persisted first so metadata edits (rename, address/port
    change, status toggle) are never lost even when the node is offline —
    e.g. when moving a node to a new IP the old address may be unreachable.

    Save always applies the VPN settings on the node. An unreachable node is
    surfaced as an explicit error so the operator knows the live sync did not
    happen; the saved record is kept and can be applied once the node is up.
    """
    existing = crud.get_node_by_id(db, node_id)
    if not existing:
        return False, "Node not found"

    geo = await run_in_threadpool(geolocate, request.address)
    api_key = request.key or existing.key

    server_ca = request.cert or await _resolve_pinned_ca(request) or getattr(existing, "server_ca", None)

    crud.update_node(db, node_id, request, geo)

    if request.cert and getattr(existing, "server_ca", None) != request.cert:
        existing.server_ca = request.cert
        db.commit()

    nr = NodeRequests(
        address=request.address,
        port=request.port,
        api_key=api_key,
        tunnel_address=request.tunnel_address or "",
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
        server_ca=server_ca,
    )

    ok = await run_in_threadpool(nr.check_node)
    if not ok:
        logger.warning("Node %s updated in DB but unreachable for live sync", request.address)
        return False, (
            "Node unreachable — the panel saved the record but could not apply the settings. "
            "Configure after registration."
        )

    configured = await run_in_threadpool(
        nr.update_config,
        tunnel_address=request.tunnel_address or "",
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
    )
    if not configured:
        logger.error("Node %s rejected configuration update", request.address)
        return True, "Node updated, but the new VPN settings could not be applied on the node."

    return True, "Node updated successfully"


async def delete_node_handler(node_id: int, db: Session) -> bool:
    from backend.node.connection import forget

    crud.delete_node(db, node_id)
    forget(node_id)
    return True


async def list_nodes_handler(db: Session) -> list:
    nodes = crud.get_all_nodes(db)
    result = []
    for n in nodes:
        result.append(
            {
                "id": n.id,
                "name": n.name,
                "address": n.address,
                "tunnel_address": n.tunnel_address,
                "protocol": n.protocol,
                "ovpn_port": n.ovpn_port,
                "port": n.port,
                "status": n.status,
                "country_code": n.country_code,
                "latitude": n.latitude,
                "longitude": n.longitude,
            }
        )
    return result


async def get_node_status_handler(node_id: int, db: Session):
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return None

    nr = node_client(node)

    started = time.perf_counter()
    nr_sessions = node_client(node)
    info, sessions, cert_pin = await asyncio.gather(
        run_in_threadpool(nr.get_node_info),
        run_in_threadpool(nr_sessions.get_sessions, None, 8),
        run_in_threadpool(_cert_pin_payload, node),
    )
    info = info if isinstance(info, dict) else {}
    sessions = sessions if isinstance(sessions, dict) else {}

    tls_verified = nr.tls_verified if nr.tls_verified is True else nr_sessions.tls_verified
    tls_mode = nr.tls_mode if nr.tls_verified is True else nr_sessions.tls_mode
    if cert_pin.get("pinned"):
        if tls_mode == "verified":
            cert_pin["match"] = True
        elif tls_mode == "unverified-self-signed":
            cert_pin["match"] = False

    return {
        "node": {
            "id": node.id,
            "name": node.name,
            "address": node.address,
            "status": node.status,
        },
        "node_info": info,
        "version_compat": node_version_compat(info.get("version")),
        "session_diagnostics": sessions,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "reachable": bool(info),
        "tls_verified": tls_verified,
        "tls_mode": tls_mode,
        "cert_pin": cert_pin,
    }


def _cert_pin_payload(node) -> dict:
    """Pinned fingerprint/expiry/issuer parsed from the stored certificate.

    The live-vs-pin verdict is filled in by the caller from the connection's
    ``tls_mode``: a request that verified against the pin saw a matching
    certificate, so no second TLS handshake is needed here.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    payload = {"pinned": False, "fingerprint": None, "expiry": None, "issuer": None, "match": None}
    pinned = getattr(node, "server_ca", None)
    if pinned and "BEGIN CERTIFICATE" in pinned:
        try:
            cert = x509.load_pem_x509_certificate(pinned.encode())
            payload["pinned"] = True
            payload["fingerprint"] = cert.fingerprint(hashes.SHA256()).hex(":").upper()
            payload["expiry"] = cert.not_valid_after_utc.isoformat()
            payload["issuer"] = cert.issuer.rfc4514_string()
        except Exception:
            pass
    return payload


async def create_user_on_all_nodes(name: str, db: Session, max_logins: int = 1, user_id: int = None):
    """Create a user on every active node concurrently.

    The numeric user ID is the OpenVPN CN and the node-side identity.
    """
    nodes = crud.get_active_nodes(db)
    uid = str(user_id) if user_id else None
    tasks = []
    for n in nodes:
        nr = node_client(n)
        tasks.append(run_bounded(nr.create_user, name, max_logins, uid))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results


async def change_user_status_on_all_nodes(
    user_id: int,
    name: str,
    status: bool,
    db: Session,
    max_logins: int = None,
    nodes: list | None = None,
) -> bool:
    """Toggle user status on every active node. Uses numeric user ID.

    ``nodes`` lets a sweep that already loaded the active list (e.g.
    enforce_user_limits) pass it in once instead of re-querying per user.
    ``None`` keeps the old behavior: query here.
    """
    nodes = crud.get_active_nodes(db) if nodes is None else nodes
    uid = str(user_id)
    tasks = []
    for n in nodes:
        nr = node_client(n)
        tasks.append(run_bounded(nr.change_user_status, name, status, max_logins, uid))
    if not tasks:
        return True
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return all(result is True for result in results)


async def set_user_limit_on_all_nodes(name: str, max_logins: int, db: Session, user_id: int = None) -> bool:
    nodes = crud.get_active_nodes(db)
    uid = str(user_id) if user_id else name
    tasks = []
    for n in nodes:
        nr = node_client(n)
        tasks.append(run_bounded(nr.set_user_limit, uid, int(max_logins or 0)))
    if not tasks:
        return True
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return all(result is True for result in results)


_REMOTE_LINE_RE = re.compile(r"^\s*remote\s+", re.IGNORECASE)


def _remote_plan(node, db: Session) -> tuple[str | None, int, list[tuple[str, int]]]:
    """Domain (or None), the node's own port, and the other nodes as fallbacks."""
    settings = crud.get_settings(db)
    domain = (getattr(settings, "panel_domain", None) or "").strip() or None
    fallbacks = [
        (n.address, int(n.ovpn_port or 0))
        for n in crud.get_all_nodes(db)
        if n.id != node.id
    ]
    return domain, int(node.ovpn_port or 0), fallbacks


def _inject_remote_lines(
    content: bytes,
    domain: str | None,
    primary_port: int,
    fallbacks: list[tuple[str, int]],
) -> bytes:
    """Rewrite the ``remote`` block of a node-generated .ovpn.

    Adds the panel domain (when configured) as the first remote and every
    other registered node as a fallback, so clients fail over across nodes
    and a node IP change no longer breaks existing configs. The node's own
    remote lines (including extra ports) stay in place.
    """
    if not domain and not fallbacks:
        return content
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content

    lines = text.splitlines()
    remote_idx = [i for i, line in enumerate(lines) if _REMOTE_LINE_RE.match(line)]
    if not remote_idx:
        return content

    out = list(lines)
    if domain:
        out.insert(remote_idx[0], f"remote {domain} {primary_port}")
        remote_idx = [i + 1 for i in remote_idx]
    fallback_lines = [f"remote {addr} {port}" for addr, port in fallbacks]
    if fallback_lines:
        pos = remote_idx[-1] + 1
        out[pos:pos] = fallback_lines

    trailing = "\n" if text.endswith("\n") else ""
    return ("\n".join(out) + trailing).encode("utf-8")


async def download_ovpn_client_from_node(user_id: int, node_id: int, db: Session):
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return None

    plan = _remote_plan(node, db)
    nr = node_client(node)
    content = await run_in_threadpool(nr.download_ovpn_bytes, str(user_id))
    if content is None:
        return None
    content = _inject_remote_lines(content, *plan)
    return Response(
        content=content,
        media_type="application/x-openvpn-profile",
        headers={"Content-Disposition": f'attachment; filename="{user_id}.ovpn"'},
    )


async def download_all_ovpn_clients_from_node(node_id: int, db: Session) -> StreamingResponse | None:
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return None

    users = crud.get_all_users(db)
    plan = _remote_plan(node, db)
    nr = node_client(node)

    buf = SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    with zipfile.ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        for user in users:
            raw = await run_in_threadpool(nr.download_ovpn_bytes, str(user.id))
            if raw:
                zf.writestr(f"{user.name}.ovpn", _inject_remote_lines(raw, *plan))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{node.name}_all_clients.zip"'},
        background=BackgroundTask(buf.close),
    )


async def delete_user_on_all_nodes(name: str, user_id: int, db: Session) -> dict:
    """Delete a user from every active node. Uses numeric user ID.

    Returns {"ok", "failed"} where ``failed`` names unreachable nodes.
    A dead node must not block panel-side deletion (its cert is already
    unusable once the node is gone; NOT_FOUND counts as success so already
    cleaned nodes never block either). Callers surface ``failed`` so the
    operator knows which nodes need attention.
    """
    nodes = crud.get_active_nodes(db)
    if not nodes:
        return {"ok": True, "failed": []}
    tasks = []
    for n in nodes:
        nr = node_client(n)
        tasks.append(run_bounded(nr.delete_user, str(user_id)))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failed = [n.name for n, r in zip(nodes, results, strict=True) if r is not True]
    return {"ok": not failed, "failed": failed}


async def reset_user_usage_on_all_nodes(user_id: int, db: Session) -> dict:
    """Zero a user's banked counters on every active node (panel reset fan-out).

    Best-effort like delete: an offline node keeps its banked file, but the
    panel already cleared its baselines, so the collector rebaselines (bills
    zero) instead of resurrecting old bytes when the node returns.
    Returns {"ok", "failed"} naming unreachable nodes.
    """
    nodes = crud.get_active_nodes(db)
    if not nodes:
        return {"ok": True, "failed": []}
    tasks = []
    for n in nodes:
        nr = node_client(n)
        tasks.append(run_bounded(nr.reset_usage, str(user_id)))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failed = [n.name for n, r in zip(nodes, results, strict=True) if r is not True]
    return {"ok": not failed, "failed": failed}
