"""Centralized authorization dependencies for the OVManager panel.

Provides reusable FastAPI dependencies for role-based and ownership-based
access control, replacing the scattered inline checks in individual routers.
"""

from fastapi import Depends, HTTPException, status

from backend.auth.auth import get_current_user
from backend.db.models import User


def require_owner(user: dict = Depends(get_current_user)):
    """Dependency: require the user to be the owner (superadmin)."""
    if user.get("type") != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires owner privileges",
        )
    return user


def require_user_access(db_user, current_user: dict) -> None:
    """Raise 403 unless ``current_user`` may touch ``db_user``.

    The single tenancy rule for per-user routes: the owner reaches every user,
    an admin only their own. Call it after loading the row, so a foreign uuid
    and a missing one are not distinguishable to the caller by this check.
    """
    if current_user.get("type") == "owner":
        return
    if db_user.owner != current_user.get("username"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this resource",
        )


def owned_by(query, current_user: dict):
    """Scope a ``User`` query to what ``current_user`` may list.

    The list counterpart of :func:`require_user_access`; the owner's query is
    returned untouched.
    """
    if current_user.get("type") == "owner":
        return query
    return query.filter(User.owner == current_user.get("username"))
