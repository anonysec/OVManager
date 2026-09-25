# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""CRUD package: per-entity modules re-exported for a stable import path.

``from backend.db import crud; crud.create_user(...)`` and
``from backend.db.crud import create_user`` both keep working.
"""

from backend.db.crud.admins import (
    Admin,
    create_admin,
    delete_admin,
    get_admin_by_telegram_id,
    get_admin_by_username,
    get_all_admins,
    it_is_admin,
    update_admin,
)
from backend.db.crud.crypto import (
    _fernet,
    _node_fernet,
    decrypt_node_key,
    encrypt_node_key,
    node_api_key,
)
from backend.db.crud.nodes import (
    Node,
    _manual_country,
    create_node,
    delete_node,
    get_active_nodes,
    get_all_nodes,
    get_node_by_id,
    get_node_by_name,
    update_node,
)
from backend.db.crud.settings import (
    Settings,
    decrypt_bot_token,
    get_bot_config,
    get_settings,
    update_bot_config,
    update_setting_timezone,
)
from backend.db.crud.users import (
    User,
    activation_blocked,
    adjust_user,
    change_user_status,
    create_user,
    delete_user,
    effective_user_defaults,
    get_all_users,
    get_expired_users,
    get_user_by_name,
    get_user_by_uuid,
    get_user_id_name_pairs,
    get_users_by_admin,
    get_users_exceeded_traffic,
    get_users_page,
    reset_user_usage,
    restore_user,
    update_user,
)

__all__ = [
    "Admin",
    "Node",
    "Settings",
    "User",
    "_fernet",
    "_manual_country",
    "_node_fernet",
    "activation_blocked",
    "adjust_user",
    "change_user_status",
    "create_admin",
    "create_node",
    "create_user",
    "decrypt_bot_token",
    "decrypt_node_key",
    "delete_admin",
    "delete_node",
    "delete_user",
    "effective_user_defaults",
    "encrypt_node_key",
    "get_active_nodes",
    "get_admin_by_telegram_id",
    "get_admin_by_username",
    "get_all_admins",
    "get_all_nodes",
    "get_all_users",
    "get_bot_config",
    "get_expired_users",
    "get_node_by_id",
    "get_node_by_name",
    "get_settings",
    "get_user_by_name",
    "get_user_by_uuid",
    "get_user_id_name_pairs",
    "get_users_by_admin",
    "get_users_exceeded_traffic",
    "get_users_page",
    "it_is_admin",
    "node_api_key",
    "reset_user_usage",
    "restore_user",
    "update_admin",
    "update_bot_config",
    "update_node",
    "update_setting_timezone",
    "update_user",
]
