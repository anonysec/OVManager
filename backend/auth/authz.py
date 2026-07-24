"""Centralized authorization dependencies for the OVManager panel.

Provides reusable FastAPI dependencies for role-based and ownership-based
access control, replacing the scattered inline checks in individual routers.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.db.engine import get_db
from backend.db import crud


def require_main_admin(user: dict = Depends(get_current_user)):
    """Dependency: require the user to be a main_admin."""
    if user.get("type") != "main_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires main admin privileges",
        )
    return user


def require_admin_or_main(user: dict = Depends(get_current_user)):
    """Dependency: require the user to be at least an admin (or main_admin)."""
    if user.get("type") not in ("admin", "main_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires admin privileges",
        )
    return user


def require_ownership(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Dependency factory: returns a function that checks user ownership.

    Usage:
        @router.get("/users/{uuid}")
        async def get_user(uuid: str, owner_check=Depends(require_ownership)):
            # owner_check(uuid) raises 403 if the current user doesn't own this user
            pass
    """
    def check(uuid: str, user_name: str = None) -> bool:
        if user.get("type") == "main_admin":
            return True
        if user.get("type") == "admin":
            if user_name is not None and user_name != user.get("username"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to access this resource",
                )
            # If user_name not provided, look up by uuid
            if user_name is None:
                db_user = crud.get_user_by_uuid(db, uuid)
                if db_user and db_user.owner != user.get("username"):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to access this resource",
                    )
            return True
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires admin privileges",
        )
    return check
