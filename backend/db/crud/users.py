# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""User CRUD: lookup, pagination, create/update, lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db.exceptions import ConflictError, NotFoundError, ValidationError
from backend.db.models import User
from backend.logger import logger
from backend.schema._input import CreateUser, UpdateUser

from .admins import it_is_admin
from .settings import get_settings


def get_all_users(db: Session):
    users = db.query(User).all()
    return users


def get_user_id_name_pairs(db: Session) -> list[tuple[str, str]]:
    """Return ``[(str(id), name), ...]`` without materialising User objects.

    Used by the live collector, which only needs the id→username mapping to
    translate a node's ``common_name`` and runs every few seconds.
    """
    return [(str(uid), name) for uid, name in db.query(User.id, User.name).all()]


def get_users_by_admin(db: Session, admin_username: str):
    users = db.query(User).filter(User.owner == admin_username).all()
    return users


def get_users_page(
    db: Session,
    *,
    owner: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list, int]:
    """DB-level search + pagination (bot + API consumers).

    The panel UI filters client-side and uses the unpaginated default;
    server-side search exists so per-keystroke bot lookups don't pull the
    whole table on every keystroke.
    """
    query = db.query(User)
    if owner is not None:
        query = query.filter(User.owner == owner)
    if search:
        query = query.filter(User.name.ilike(f"%{search}%"))
    total = query.count()
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 100), 500))
    items = query.order_by(User.id).offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def get_user_by_name(db: Session, name: str):
    user = db.query(User).filter(User.name == name).first()
    if user:
        return user
    return None


def get_user_by_uuid(db: Session, uuid: str):
    user = db.query(User).filter(User.uuid == uuid).first()
    if user:
        return user
    return None


def effective_user_defaults(db: Session, admin_username: str | None = None) -> dict:
    """New-user defaults for one admin: their override, else the owner's global.

    The owner sets the global plan in Settings (the Telegram bot block); an
    admin may override days/traffic/devices for the users they create. NULL
    override always inherits.

    ``traffic_gb`` is a prefill hint, not a server-side cap: ``CreateUser.total``
    is None-or-bytes (None means unlimited, which the bot sends for "0 GB"), so
    create_user cannot distinguish "no cap" from "unset" and must not invent one.
    """
    global_defaults = {"days": 30, "traffic_gb": 100, "max_users": 1}
    try:
        settings = get_settings(db)
        if settings is not None:
            global_defaults = {
                "days": int(getattr(settings, "default_days", 30) or 30),
                "traffic_gb": int(getattr(settings, "default_traffic_gb", 100) or 100),
                "max_users": int(getattr(settings, "default_max_users", 1) or 1),
            }
    except Exception:
        pass

    resolved = dict(global_defaults)
    if admin_username:
        admin = it_is_admin(db, admin_username)
        if admin is not None:
            for key, attr in (
                ("days", "default_days"),
                ("traffic_gb", "default_traffic_gb"),
                ("max_users", "default_max_users"),
            ):
                value = getattr(admin, attr, None)
                if value is not None:
                    resolved[key] = int(value)
    return resolved


def create_user(db: Session, request: CreateUser, owner: str):
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    username = request.name.replace(" ", "_")

    # Omitted values fall back to the creating admin's effective defaults
    # (their override, else the owner's global bot plan), so raw API and bot
    # callers do not have to replicate the plan logic.
    # total=None explicitly means unlimited (the bot sends None for 0 GB).
    defaults = effective_user_defaults(db, owner)
    expiry = request.expiry_date
    if expiry is None:
        expiry = _date.today() + _timedelta(days=defaults["days"])

    tag = (request.tag or "").strip() or None
    new_user = User(
        name=username,
        expiry_date=expiry,
        total=request.total,
        max_logins=(
            defaults["max_users"] if request.max_logins is None else request.max_logins
        ),
        owner=owner,
        tag=tag,
        uuid=str(uuid4()),
    )

    db.add(new_user)
    try:
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise ConflictError("User", "name", username) from None
    logger.info("user created successfully: %s", request.name)
    return new_user


def activation_blocked(user: User) -> str | None:
    """Reason this user must not be active, or None when activation is fine.

    An expired or out-of-traffic account must never be active, even when an
    admin flips the status switch on; both the edit form and the status
    endpoint share this rule so they cannot disagree.
    """
    used = user.used or 0
    if user.expiry_date and user.expiry_date < datetime.now(UTC).date():
        return "expired"
    if user.total is not None and user.total <= used:
        return "out of traffic"
    return None


def update_user(db: Session, uuid: str, request: UpdateUser):
    user = db.query(User).filter(User.uuid == uuid).first()
    if not user:
        raise NotFoundError("User", uuid)

    # Only touch what the caller actually sent. `model_fields_set` separates
    # "omitted" from "explicitly null" — the distinction matters because
    # total=None legitimately means unlimited, so we cannot use None alone as
    # the "not supplied" sentinel.
    #
    # This used to assign expiry_date and total unconditionally, so any partial
    # update silently cleared the fields it did not mention. A client that
    # posts only {"expiry_date": ...} used to wipe `total` and convert a
    # quota-limited account to unlimited traffic — returning 200.
    # Sending {"expiry_date": null} likewise hit a NOT NULL constraint and 500ed.
    sent = request.model_fields_set

    if "expiry_date" in sent:
        if request.expiry_date is None:
            # The column is NOT NULL; reject explicitly rather than 500 in the
            # driver. UpdateUser types this Optional only so the field can be
            # omitted from a partial update.
            raise ValidationError("expiry_date", "expiry_date cannot be null")
        user.expiry_date = request.expiry_date
    if "total" in sent:
        user.total = request.total
    if "max_logins" in sent and request.max_logins is not None:
        user.max_logins = request.max_logins
    if "tag" in sent:
        user.tag = (request.tag or "").strip() or None

    # Evaluate the activation guards against the POST-UPDATE row, not the
    # request: with partial updates the request may not carry these fields.
    # Manual status (from the edit modal checkbox) wins, but expiry/traffic
    # violations still force-disable: an expired or out-of-traffic account
    # must never be active even if the admin flipped the switch on.
    requested_status = user.is_active if request.status is None else bool(request.status)
    user.is_active = requested_status and activation_blocked(user) is None

    db.commit()
    db.refresh(user)
    return {"detail": "User updated successfully"}


def change_user_status(db: Session, uuid: str, status: bool) -> bool:
    user = db.query(User).filter(User.uuid == uuid).first()
    if not user:
        logger.error("change_user_status: user not found for uuid=%s", uuid)
        return False
    try:
        user.is_active = status
        db.commit()
        db.refresh(user)
        return True
    except Exception as e:
        logger.error("Error changing status for user %s on db: %s", user.name, e)
        return False


def reset_user_usage(db: Session, uuid: str) -> bool:
    user = db.query(User).filter(User.uuid == uuid).first()
    if not user:
        return False

    user.used = 0
    # Reset the per-node baselines too, so the next sync starts counting from
    # the nodes' current cumulative values instead of producing a huge delta.
    user.last_node_usage = 0
    user.node_usage = "{}"
    db.commit()
    return True


def get_expired_users(db: Session):
    return db.query(User).filter(User.expiry_date < datetime.now(UTC).date(), User.is_active).all()


def get_users_exceeded_traffic(db: Session):
    # Exclude users with NULL total (unlimited traffic)
    return db.query(User).filter(User.total.isnot(None), User.used > User.total, User.is_active).all()


def delete_user(db: Session, name: str):
    user = db.query(User).filter(User.name == name).first()
    if not user:
        raise NotFoundError("User", name)

    # Daily rows key by id and SQLite reuses ids — orphaned bytes would leak
    # into an unrelated future user's history graph.
    from sqlalchemy import text as _text

    db.execute(_text("DELETE FROM user_traffic_daily WHERE user_id = :uid"), {"uid": user.id})
    db.delete(user)
    db.commit()


# admins crud


def restore_user(db: Session, snapshot: dict):
    """Re-insert a deleted user with its original UUID (undo delete)."""
    from uuid import uuid4

    expiry = snapshot.get("expiry_date")
    if isinstance(expiry, str) and expiry:
        from datetime import date as _date

        try:
            expiry = _date.fromisoformat(expiry[:10])
        except ValueError:
            expiry = None

    new_user = User(
        name=snapshot["name"],
        uuid=snapshot.get("uuid") or str(uuid4()),
        total=snapshot.get("total"),
        used=snapshot.get("used"),
        # Restore the per-node traffic baselines too: without them the next
        # collector poll rebaselines to the node's current counters and any
        # traffic consumed between delete and undo is never billed.
        node_usage=snapshot.get("node_usage") or "{}",
        last_node_usage=int(snapshot.get("last_node_usage") or 0),
        max_logins=int(snapshot.get("max_logins") or 1),
        expiry_date=expiry,
        is_active=bool(snapshot.get("is_active", True)),
        owner=snapshot.get("owner") or "",
    )
    db.add(new_user)
    try:
        db.commit()
        db.refresh(new_user)
    except IntegrityError as exc:
        db.rollback()
        # Only a duplicate name is a real conflict; anything else (e.g. a
        # corrupt snapshot) must not masquerade as "already exists".
        if "users.name" in str(exc):
            raise ConflictError("User", "name", snapshot["name"]) from None
        raise ValidationError("user", f"could not restore user: {exc}") from None
    return new_user


def adjust_user(db: Session, uuid: str, days: int = 0, add_bytes: int = 0, owner: str | None = None) -> User | None:
    """Extend expiry (+days) and/or add traffic quota (+add_bytes) for one user.

    When ``owner`` is given (non-owner admins), the user must belong to that
    admin — a request must never cross tenant boundaries. Unauthorized UUIDs
    return None without revealing that they exist.
    """
    from datetime import timedelta

    query = db.query(User).filter(User.uuid == uuid)
    if owner is not None:
        query = query.filter(User.owner == owner)
    user = query.first()
    if user is None:
        return None
    if days:
        from datetime import date as _date

        # A user without expiry is unlimited-time: extending from today.
        # Previously this silently did nothing when expiry_date was NULL.
        base = user.expiry_date or _date.today()
        user.expiry_date = base + timedelta(days=days)
    if add_bytes:
        user.total = (user.total or 0) + add_bytes
    db.commit()
    db.refresh(user)
    return user

