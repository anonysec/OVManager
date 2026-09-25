# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Schema package: one module for request + response models.

``from backend.schema import CreateUser, ResponseModel`` replaces the old
``backend.schema._input`` / ``backend.schema.output`` imports.
"""

from __future__ import annotations

from backend.schema.models import (
    AdminCreate,
    Admins,
    AdminStatusUpdate,
    AdminUpdate,
    CreateUser,
    NodeCreate,
    ResponseModel,
    ServerInfo,
    Settings,
    StatusToggle,
    UpdateUser,
    Users,
)

__all__ = [
    "AdminCreate",
    "AdminStatusUpdate",
    "AdminUpdate",
    "Admins",
    "CreateUser",
    "NodeCreate",
    "ResponseModel",
    "ServerInfo",
    "Settings",
    "StatusToggle",
    "UpdateUser",
    "Users",
]
