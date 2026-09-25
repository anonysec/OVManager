# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Node CRUD."""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.exceptions import NotFoundError
from backend.db.models import Node
from backend.schema import NodeCreate


def get_all_nodes(db: Session):
    nodes = db.query(Node).all()
    return nodes


def get_active_nodes(db: Session):
    """Return only nodes with status=True."""
    return db.query(Node).filter(Node.status == True).all()  # noqa: E712


def get_node_by_id(db: Session, id: int):
    return db.query(Node).filter(Node.id == id).first()


def get_node_by_name(db: Session, name: str):
    return db.query(Node).filter(Node.name == name).first()


def _manual_country(request: NodeCreate) -> str | None:
    """Manual country override from the form, normalized — or None for auto."""
    raw = (request.country_code or "").strip().upper()
    return raw or None


def create_node(db: Session, request: NodeCreate, geolocation: dict = None):
    manual = _manual_country(request)
    new_node = Node(
        name=request.name,
        address=request.address,
        tunnel_address=request.tunnel_address,
        ovpn_port=request.ovpn_port,
        protocol=request.protocol,
        port=request.port,
        key=request.key,
        status=request.status,
        use_tls=request.use_tls,
        country_code=manual or (geolocation.get("country_code") if geolocation else None),
        latitude=None if manual else (geolocation.get("latitude") if geolocation else None),
        longitude=None if manual else (geolocation.get("longitude") if geolocation else None),
    )

    db.add(new_node)
    db.commit()
    db.refresh(new_node)
    return new_node


def update_node(db: Session, node_id: int, request: NodeCreate, geolocation: dict = None):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise NotFoundError("Node", str(node_id)) from None

    node.name = request.name
    node.address = request.address
    node.tunnel_address = request.tunnel_address
    node.ovpn_port = request.ovpn_port
    node.protocol = request.protocol
    node.port = request.port
    manual = _manual_country(request)
    if manual:
        # Operator override wins; stale auto coords are cleared so the UI
        # never mixes a manual country with coordinates from another one.
        node.country_code = manual
        node.latitude = None
        node.longitude = None
    elif geolocation:
        node.country_code = geolocation.get("country_code")
        node.latitude = geolocation.get("latitude")
        node.longitude = geolocation.get("longitude")
    node.status = request.status
    node.use_tls = request.use_tls

    # Only overwrite API key if a non-empty value is provided
    if request.key and request.key.strip():
        node.key = request.key.strip()

    db.commit()
    db.refresh(node)
    return node


def delete_node(db: Session, id: int):
    node = db.query(Node).filter(Node.id == id).first()
    if not node:
        raise NotFoundError("Node", str(id))
    db.delete(node)
    db.commit()
    return {"detail": "Node deleted successfully"}


# settings crud
