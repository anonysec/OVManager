# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm restore`: put a stored panel backup back.

The restore itself is the panel's own transaction
(``backend.routers.maintenance.restore_stored_backup``), reused unchanged: it
stages and verifies a candidate, copies the live database to a fresh
``ovmanager-pre-restore-*`` bundle before it activates anything, and rolls back
to that copy when the activated database fails. This module is the operator
front end — list, name, report.

The owner credential is a database row, so restoring the database restores it
by definition. Nothing here reads or writes a credential in .env.
"""

from __future__ import annotations

import os
from datetime import datetime

from cli.env import Install


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def list_backups(install: Install) -> dict:
    """Every restorable backup, newest first, with its date and size."""
    _ = install
    try:
        import backend.routers.maintenance as maintenance
    except Exception as exc:
        return {"ok": False, "error": f"Backend not available: {exc}"}
    try:
        items = maintenance.stored_backups()
        directory = str(maintenance.BACKUP_DIR)
    except Exception as exc:
        return {"ok": False, "error": f"Could not list backups: {exc}"}
    return {"ok": True, "backups": items, "dir": directory}


def restore_backup(install: Install, name: str) -> dict:
    """Restore one stored backup by name (the transaction is the backend's)."""
    if not os.path.isdir(install.install_dir):
        return {"ok": False, "installed": False, "error": f"Not installed ({install.install_dir} missing)"}
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return {"ok": False, "error": f"Invalid backup name: {name}"}
    try:
        import backend.routers.maintenance as maintenance
    except Exception as exc:
        return {"ok": False, "error": f"Backend not available: {exc}"}
    try:
        result = maintenance.restore_stored_backup(name, actor="ovm-cli")
    except Exception as exc:
        return {"ok": False, "error": f"Restore failed: {exc}"}
    data = getattr(result, "data", None) or {}
    if not getattr(result, "success", False):
        return {
            "ok": False,
            "error": str(getattr(result, "msg", "Restore failed")),
            "safety_backup": data.get("safety_backup"),
            "rolled_back": data.get("rolled_back"),
        }
    return {
        "ok": True,
        "name": name,
        "safety_backup": data.get("safety_backup"),
        "message": str(getattr(result, "msg", "Database restored")),
    }


def render_list_text(data: dict) -> str:
    """Human rows matching the manager's listing: name, date, size."""
    if not data.get("ok"):
        return f"  Error: {data.get('error', 'could not list backups')}\n"
    backups = data.get("backups") or []
    directory = data.get("dir", "")
    if not backups:
        return f"  No data backups in {directory} — create one with: ovm backup\n"
    width = max(len(item["name"]) for item in backups)
    lines = [f"  Data backups in {directory}"]
    for item in backups:
        when = datetime.fromtimestamp(item["mtime"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"  {item['name']:<{width}}  {when}  {_human_size(item['size'])}")
    lines.append("")
    lines.append("  Restore one with: ovm restore <name>")
    return "\n".join(lines) + "\n"


def render_restore_text(data: dict) -> str:
    """What was restored, and the copy that undoes it."""
    if not data.get("ok"):
        text = f"  Error: {data.get('error', 'restore failed')}\n"
        if data.get("safety_backup"):
            text += f"  {'Safety copy':<14} {data['safety_backup']}\n"
        return text
    lines = [f"  {'Restored':<14} {data.get('name', '')}"]
    if data.get("safety_backup"):
        lines.append(f"  {'Safety copy':<14} {data['safety_backup']}")
    return "\n".join(lines) + "\n"
