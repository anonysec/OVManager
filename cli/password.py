# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm auth reset` in Python: rewrite the owner credential in the database.

The owner is an ordinary ``admins`` row (see the v16 migration), so the
credential is updated there — never in ``.env``. Never echoes the value.
"""

from __future__ import annotations

import os

from backend.logger import logger
from cli import render


def validate(password: str) -> str | None:
    """Return a human reason when ``password`` violates panel policy, else None.

    The rule itself lives in backend/validation.py, next to the other shared
    input validators: the browser claim and this command must not drift.
    """
    from backend.validation import password_problem

    return password_problem(password)


def hash_password(password: str) -> str | None:
    """Bcrypt-hash via the panel's own hasher; None when unavailable."""
    try:
        from backend.auth.hash import hash_password as _hash

        return _hash(password)
    except Exception:
        return None


def reset_password(install_dir: str, password: str | None = None, data_dir: str | None = None) -> dict:
    """Set the owner's bcrypt hash in the ``admins`` row at ``data_dir``.

    ``install_dir`` is only read for ADMIN_USERNAME and DATA_DIR; the .env file
    itself is never written. The password comes from the argument or, when
    omitted, from the OVM_ADMIN_PASS environment variable. The environment is
    how the manager passes it: a command-line argument would be visible in `ps`
    to every user on the box, and it would land in the shell history.

    Returns a result dict (never raises, never echoes the password).
    """
    if password is None:
        password = os.environ.get("OVM_ADMIN_PASS")
    if not password:
        return {"ok": False, "error": "No password given (set OVM_ADMIN_PASS or pass --admin-pass)"}
    reason = validate(password)
    if reason is not None:
        return {"ok": False, "error": f"Admin password {reason}"}
    if not os.path.isdir(install_dir):
        return {"ok": False, "error": f"Not installed ({install_dir} missing) — nothing to reset."}

    hashed = hash_password(password)
    if not hashed:
        return {"ok": False, "error": "Password hashing is unavailable — is the panel environment installed?"}

    if os.path.dirname(os.path.abspath(install_dir)) == os.path.abspath(install_dir):
        return {"ok": False, "error": f"Refusing to use {install_dir} as an install directory"}
    env_file = os.path.join(install_dir, ".env")
    if not os.path.isfile(env_file):
        return {"ok": False, "error": f"Config not found: {env_file} — install OVManager first."}

    if data_dir is None:
        data_dir = _data_dir_from_env(env_file)
    if data_dir is None:
        return {"ok": False, "error": f"DATA_DIR is not set in {env_file} — cannot locate the database."}

    owner = _owner_username(env_file)
    if not owner:
        return {"ok": False, "error": "ADMIN_USERNAME is not set — cannot tell which row is the owner."}

    written = _write_owner_hash(data_dir, hashed, owner)
    if not written.get("ok"):
        return written
    return {"ok": True, "scope": "database", "username": owner}


def _owner_username(env_file: str) -> str:
    """The owner's username, read from the installed .env without touching config."""
    try:
        with open(env_file, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("ADMIN_USERNAME="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def _data_dir_from_env(env_file: str) -> str | None:
    try:
        with open(env_file, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("DATA_DIR="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def _write_owner_hash(data_dir: str, hashed: str, owner: str) -> dict:
    """Set the owner row's bcrypt hash in the database at ``data_dir``.

    Opens its own engine rather than the process-wide one: the installed data
    directory is not the caller's, and reaching for the shared engine would
    mean repointing the panel's own database at it.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.db.models import Admin

    db_path = os.path.join(data_dir, "ovmanager.db")
    if not os.path.isfile(db_path):
        return {"ok": False, "error": f"Panel database not found at {db_path} — is the panel installed?"}

    try:
        engine = create_engine(f"sqlite:///{db_path}")
    except Exception as exc:
        return {"ok": False, "error": f"Could not open the panel database: {exc}"}

    db = sessionmaker(bind=engine)()
    try:
        row = db.query(Admin).filter(Admin.username == owner).first()
        if row is None:
            db.add(Admin(username=owner, password=hashed, disabled=False))
        else:
            row.password = hashed
            row.disabled = False
        db.commit()

        try:
            from backend.auth.sessions import revoke_user_sessions

            revoked = revoke_user_sessions(db, owner)
        except Exception:
            logger.warning("password reset: could not revoke sessions for %s", owner)
            revoked = None
    except Exception as exc:
        db.rollback()
        return {"ok": False, "error": f"Could not update the owner credential: {exc}"}
    finally:
        db.close()
        engine.dispose()
    return {"ok": True, "username": owner, "sessions_revoked": revoked}


def render_text(data: dict) -> str:
    if not data.get("ok"):
        return render.block([render.failed(data.get("error", "password not changed"))])
    owner = data.get("username", "the owner")
    rows = [
        render.ok(f"owner password updated for {owner}"),
        render.hint("stored in the panel database — .env is not edited"),
    ]
    n = data.get("sessions_revoked")
    if n is None:
        rows.append(render.hint("could not confirm session revocation — check the panel logs"))
    elif isinstance(n, int):
        rows.append(
            render.hint(f"revoked {n} active session{'s' if n != 1 else ''} — every device must sign in again")
            if n
            else render.hint("no active sessions to revoke")
        )
    return render.block(rows)
