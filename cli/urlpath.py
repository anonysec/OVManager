# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm url reset` in Python: clear the panel prefix via main.py.

Mirrors manager.sh reset_urlpath_now (native python vs docker exec).
"""

from __future__ import annotations

import os
import subprocess

from cli import render


def current() -> dict:
    """What the running panel is actually serving, which is not .env.

    URLPATH has been a settings row since v16; `.env` is only the seed the
    installer wrote. So an operator who edits `.env` and sees nothing change has
    not made a mistake — and the only way to tell them that is to read the live
    value rather than the file. Never raises.
    """
    import os as _os

    _os.environ.setdefault("DATA_DIR", _os.environ.get("OVM_DATA_DIR", "/var/lib/ovmanager"))
    try:
        from backend.urlpath import get_urlpath, reserved_prefixes

        prefix = (get_urlpath() or "").strip("/")
        return {
            "ok": True,
            "prefix": prefix,
            "reserved": sorted(reserved_prefixes()),
            "owner": _os.environ.get("ADMIN_USERNAME", ""),
        }
    except Exception as exc:  # an unreadable database is a fact, not a crash
        return {"ok": False, "error": f"Could not read the live url path: {exc}"}


def set_prefix(value: str) -> dict:
    """Persist a prefix, or rotate one. Never raises.

    Validation is the panel's, not this command's: `set_urlpath` refuses the
    reserved prefixes that would shadow a live route, and doing that check in
    two places is how they would disagree.
    """
    try:
        from backend.urlpath import set_urlpath

        stored = set_urlpath((value or "").strip("/"))
        return {"ok": True, "prefix": stored}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"Could not set the url path: {exc}"}


def reset(install_dir: str, compose_file: str, in_container: bool = False) -> dict:
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
        return render.block([render.failed(data.get("error", "reset failed"))])
    return render.block([render.ok("panel url prefix cleared — served at /")])


def render_current(data: dict) -> str:
    """The live prefix and where it came from."""
    if not data.get("ok"):
        return render.block([render.failed(data.get("error", "could not read the url path"))])
    return render.block(render.rows([("Prefix", data.get("prefix") or "none — served at /"), ("Source", "database")]))


def render_set(data: dict) -> str:
    if not data.get("ok"):
        return render.block([render.failed(data.get("error", "could not set the url path"))])
    prefix = data.get("prefix") or ""
    if prefix:
        return render.block([render.ok("url path set"), render.kv("Prefix", prefix)])
    return render.block([render.ok("url path cleared — the panel is served at /")])
