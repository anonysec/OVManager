# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm reset-urlpath` in Python: clear the panel prefix via main.py.

Mirrors manager.sh reset_urlpath_now (native python vs docker exec).
"""

from __future__ import annotations

import os
import subprocess


def reset_urlpath(install_dir: str, compose_file: str, in_container: bool = False) -> dict:
    """Run the panel's own --reset-urlpath entrypoint. Never raises.

    `in_container` means we are already inside the panel container, where
    `docker exec` cannot work (no docker CLI) — but main.py is right here, so
    run it directly.
    """
    if not os.path.isdir(install_dir):
        return {"ok": False, "error": f"Not installed ({install_dir} missing)"}
    if os.path.isfile(compose_file) and not in_container:
        argv = ["docker", "exec", "ovmanager", "/app/.venv/bin/python", "main.py", "--reset-urlpath"]
    else:
        argv = [os.path.join(install_dir, ".venv", "bin", "python"), "main.py", "--reset-urlpath"]
    try:
        completed = subprocess.run(argv, cwd=install_dir, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        return {"ok": False, "error": f"Reset failed: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"Reset failed: {exc}"}
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip().splitlines()
        return {"ok": False, "error": f"Reset failed: {detail[-1] if detail else 'unknown error'}"}
    return {"ok": True}


def render_text(data: dict) -> str:
    if not data.get("ok"):
        return f"  Error: {data.get('error')}\n"
    return "  Panel path reset — the panel is served at / again\n"
