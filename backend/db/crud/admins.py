# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Admin CRUD."""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.auth.hash import hash_password
from backend.db.models import Admin
from backend.schema import AdminCreate


def get_admin_by_username(db: Session, username: str):
    admin = db.query(Admin).filter(Admin.username == username).first()
    return admin


def create_admin(db: Session, admin: AdminCreate):
    hashed_password = hash_password(admin.password)
    new_admin = Admin(
        username=admin.username,
        password=hashed_password,
        telegram_id=admin.telegram_id,
        username_prefix=admin.username_prefix,
        default_days=admin.default_days,
        default_traffic_gb=admin.default_traffic_gb,
        default_max_users=admin.default_max_users,
    )
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)
    return new_admin


def update_admin(db: Session, existing_admin: Admin, admin: AdminCreate):
    existing_admin.password = hash_password(admin.password)
    existing_admin.telegram_id = admin.telegram_id
    existing_admin.username_prefix = admin.username_prefix

    db.commit()
    db.refresh(existing_admin)
    return existing_admin


def get_admin_by_telegram_id(db: Session, tg_id: int):
    return db.query(Admin).filter(Admin.telegram_id == tg_id).first()


def get_all_admins(db: Session):
    admins = db.query(Admin).all()
    return admins


def it_is_admin(db: Session, username: str):
    """Return the Admin object if found, else None."""
    return db.query(Admin).filter(Admin.username == username).first()


def delete_admin(db: Session, admin: Admin):
    db.delete(admin)
    db.commit()
    return True


# nodes crud

