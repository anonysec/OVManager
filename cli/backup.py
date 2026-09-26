# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm backup` and `ovm auto-backup` in Python.

Mirrors ``manager.sh`` ``backup_now()`` and ``auto_backup_cli()``:

- ``backup_now`` creates one panel backup via
  ``backend.routers.maintenance.create_panel_backup`` (default keep 14,
  same as ``BACKUP_KEEP:-14`` in bash).
- ``auto_backup`` reads/writes the panel schedule
  (``Settings.auto_backup_enabled/_time/_keep``) via ``SessionLocal``.
  Time is validated with the same ``^([01]\\d|2[0-3]):[0-5]\\d$`` regex
  the API uses; keep is validated as 1-500 (same as bash + API).
"""

from __future__ import annotations

import json
import os
import re

from cli.env import Install

_AUTO_BACKUP_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_AUTO_BACKUP_KEEP_MIN = 1
_AUTO_BACKUP_KEEP_MAX = 500
_DEFAULT_BACKUP_KEEP = 14
_DEFAULT_AUTO_TIME = "03:30"
_DEFAULT_AUTO_KEEP = 50


def _coerce_keep(raw) -> tuple[int | None, str | None]:
    """Return (keep, error); error is None on success."""
    if raw is None:
        return None, None
    text = str(raw).strip()
    if not re.fullmatch(r"[0-9]+", text):
        return None, f"Invalid --keep '{raw}' (1-500)"
    try:
        keep = int(text)
    except ValueError:
        return None, f"Invalid --keep '{raw}' (1-500)"
    if not (_AUTO_BACKUP_KEEP_MIN <= keep <= _AUTO_BACKUP_KEEP_MAX):
        return None, f"Invalid --keep '{raw}' (1-500)"
    return keep, None


def backup_now(install: Install, keep=None) -> dict:
    """Create a panel backup now (tests assert on this dict, not stdout)."""
    if keep is None:
        keep_n = _DEFAULT_BACKUP_KEEP
    else:
        parsed, error = _coerce_keep(keep)
        if error is not None:
            return {"ok": False, "error": error}
        keep_n = parsed if parsed is not None else _DEFAULT_BACKUP_KEEP
    if not os.path.isdir(install.install_dir):
        return {"ok": False, "installed": False, "error": f"Not installed ({install.install_dir} missing)"}
    try:
        import backend.routers.maintenance as maintenance
    except Exception as exc:
        return {"ok": False, "error": f"Backend not available: {exc}"}
    try:
        created = maintenance.create_panel_backup(keep_n)
    except Exception as exc:
        return {"ok": False, "error": f"Backup failed: {exc}"}
    if not created:
        return {"ok": False, "error": "Backup skipped because the panel database was not found"}
    path = str(created)
    return {"ok": True, "path": path, "filename": os.path.basename(path), "keep": keep_n}


def auto_backup(action: str | None, install: Install, time: str | None = None, keep=None) -> dict:
    """Read or update the panel auto-backup schedule (no printing)."""
    _ = install
    act = action.strip() if isinstance(action, str) and action.strip() else "status"
    if act not in ("status", "on", "off"):
        return {"ok": False, "error": "Usage: ovm auto-backup on [--time HH:MM] [--keep N] | off | status"}
    if time is not None:
        text = str(time).strip()
        if not _AUTO_BACKUP_TIME_RE.match(text):
            return {"ok": False, "error": f"Invalid time '{time}' (use HH:MM)"}
        time = text
    keep_n: int | None = None
    if keep is not None:
        parsed, error = _coerce_keep(keep)
        if error is not None:
            return {"ok": False, "error": error}
        keep_n = parsed
    try:
        import backend.db.engine as engine_mod
        import backend.db.models as models_mod
    except Exception as exc:
        return {"ok": False, "error": f"Backend not available: {exc}"}
    session_factory = engine_mod.SessionLocal
    settings_cls = models_mod.Settings
    db = None
    try:
        db = session_factory()
        row = db.query(settings_cls).first()
        if row is None:
            row = settings_cls(port=1194, protocol="tcp")
            db.add(row)
            db.flush()
        if act == "status":
            return {
                "ok": True,
                "enabled": bool(getattr(row, "auto_backup_enabled", False)),
                "time": getattr(row, "auto_backup_time", None) or _DEFAULT_AUTO_TIME,
                "keep": int(getattr(row, "auto_backup_keep", _DEFAULT_AUTO_KEEP) or _DEFAULT_AUTO_KEEP),
            }
        if act == "off":
            row.auto_backup_enabled = False
            db.commit()
            return {
                "ok": True,
                "enabled": False,
                "time": getattr(row, "auto_backup_time", None) or _DEFAULT_AUTO_TIME,
                "keep": int(getattr(row, "auto_backup_keep", _DEFAULT_AUTO_KEEP) or _DEFAULT_AUTO_KEEP),
            }
        row.auto_backup_enabled = True
        if time is not None:
            row.auto_backup_time = time
        if keep_n is not None:
            row.auto_backup_keep = keep_n
        db.commit()
        try:
            db.refresh(row)
        except Exception:
            pass
        return {
            "ok": True,
            "enabled": True,
            "time": getattr(row, "auto_backup_time", None) or _DEFAULT_AUTO_TIME,
            "keep": int(getattr(row, "auto_backup_keep", _DEFAULT_AUTO_KEEP) or _DEFAULT_AUTO_KEEP),
        }
    except Exception as exc:
        try:
            if db is not None:
                db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"Auto-backup update failed: {exc}"}
    finally:
        try:
            if db is not None:
                db.close()
        except Exception:
            pass


def render_backup_text(data: dict) -> str:
    """Human row matching manager.sh backup_now ("Verified backup ...")."""
    if not data.get("ok"):
        return f"  Error: {data.get('error', 'backup failed')}\n"
    return f"  Verified backup  {data.get('path', '')}\n"


def render_backup_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_auto_backup_text(data: dict) -> str:
    """Human rows for the panel auto-backup schedule (kv layout)."""
    if not data.get("ok"):
        return f"  Error: {data.get('error', 'auto-backup failed')}\n"
    state = "enabled" if data.get("enabled") else "disabled"
    lines = [
        f"  {'Auto backup':<14} {state}",
        f"  {'Time':<14} {data.get('time', _DEFAULT_AUTO_TIME)}",
        f"  {'Keep':<14} {data.get('keep', _DEFAULT_AUTO_KEEP)}",
    ]
    if not data.get("enabled"):
        lines.append(f"  {'Enable':<14} ovm auto-backup on")
    return "\n".join(lines) + "\n"


def render_auto_backup_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
