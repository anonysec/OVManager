# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth.authz import require_owner
from backend.auth.hash import hash_password
from backend.db import crud
from backend.db.engine import get_db
from backend.schema._input import AdminCreate, AdminUpdate
from backend.schema.output import Admins, ResponseModel

router = APIRouter(prefix="/admin", tags=["Admins"])


@router.get("/", response_model=ResponseModel)
async def get_all_admins(db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    from backend.db.models import User as _User

    # Single GROUP BY query instead of O(n×m) Python loop
    counts = dict(db.query(_User.owner, func.count(_User.id)).group_by(_User.owner).all())
    result = crud.get_all_admins(db)
    admin_list = []
    for admin in result:
        admin_data = Admins.model_validate(admin)
        admin_data.users_count = counts.get(admin.username, 0)
        admin_list.append(admin_data)

    return ResponseModel(
        success=True,
        msg="Admins retrieved successfully",
        data=admin_list,
    )


@router.post("/", response_model=ResponseModel)
async def create_admin(
    admin: AdminCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    existing_admin = crud.get_admin_by_username(db, username=admin.username)
    if existing_admin:
        return ResponseModel(success=False, msg="Admin with this username already exists", data=None)

    new_admin = crud.create_admin(db, admin)
    return ResponseModel(
        success=True,
        msg="Admin created successfully",
        data=Admins.model_validate(new_admin),
    )


@router.put("/")
async def update_admin(
    admin: AdminUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    existing_admin = crud.get_admin_by_username(db, username=admin.username)
    if not existing_admin:
        return ResponseModel(success=False, msg="Admin not found", data=None)

    if admin.password:
        existing_admin.password = hash_password(admin.password)
    if admin.telegram_id is not None:
        existing_admin.telegram_id = admin.telegram_id
    elif "telegram_id" in admin.model_dump(exclude_unset=True) and admin.telegram_id is None:
        existing_admin.telegram_id = None
    if admin.username_prefix is not None:
        existing_admin.username_prefix = admin.username_prefix
    elif "username_prefix" in admin.model_dump(exclude_unset=True) and admin.username_prefix is None:
        existing_admin.username_prefix = None

    db.commit()
    db.refresh(existing_admin)
    return ResponseModel(
        success=True,
        msg="Admin updated successfully",
        data=Admins.model_validate(existing_admin),
    )


@router.delete("/{username}")
async def delete_admin(
    username: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    existing_admin = crud.get_admin_by_username(db, username=username)
    if not existing_admin:
        return ResponseModel(success=False, msg="Admin not found", data=None)

    # Kill the admin's live sessions immediately — deleting the row alone
    # would leave their bearer tokens valid until idle expiry.
    from backend.auth.sessions import revoke_user_sessions

    revoke_user_sessions(db, username)
    crud.delete_admin(db, existing_admin)
    return ResponseModel(
        success=True,
        msg="Admin deleted successfully",
        data=None,
    )
