"""Role-based and ownership-based FastAPI authorization dependencies."""

from fastapi import Depends, HTTPException, status

from backend.auth.auth import get_current_user
from backend.db.models import User


def require_owner(user: dict = Depends(get_current_user)):
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
    """The list counterpart of :func:`require_user_access`."""
    if current_user.get("type") == "owner":
        return query
    return query.filter(User.owner == current_user.get("username"))
