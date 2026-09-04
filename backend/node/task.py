# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Backward-compatible re-exports for node operations.

Split into: node/ops.py, node/sync.py, node/diagnostics.py.
Kept as a thin facade so imports like
``from backend.node.task import sync_all_user_limits`` keep working.
"""

from .diagnostics import (
    disconnect_user_on_all_nodes,
    get_active_connection_counts,
    get_user_session_diagnostics,
    login_diagnostics,
    login_health_summary,
)
from .ops import (
    add_node_handler,
    change_user_status_on_all_nodes,
    create_user_on_all_nodes,
    delete_node_handler,
    delete_user_on_all_nodes,
    download_all_ovpn_clients_from_node,
    download_ovpn_client_from_node,
    get_node_status_handler,
    list_nodes_handler,
    set_user_limit_on_all_nodes,
    update_node_handler,
)
from .sync import (
    clean_global_mlogin_registry,
    clean_stale_sessions_all_nodes,
    get_users_used_traffic,
    sync_all_user_limits,
)

__all__ = [
    "add_node_handler",
    "update_node_handler",
    "delete_node_handler",
    "list_nodes_handler",
    "get_node_status_handler",
    "create_user_on_all_nodes",
    "change_user_status_on_all_nodes",
    "set_user_limit_on_all_nodes",
    "download_ovpn_client_from_node",
    "download_all_ovpn_clients_from_node",
    "delete_user_on_all_nodes",
    "get_users_used_traffic",
    "sync_all_user_limits",
    "clean_stale_sessions_all_nodes",
    "clean_global_mlogin_registry",
    "get_active_connection_counts",
    "get_user_session_diagnostics",
    "disconnect_user_on_all_nodes",
    "login_health_summary",
    "login_diagnostics",
]
