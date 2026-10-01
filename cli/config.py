# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm config`: every effective setting, and where each one comes from.

The question this exists to answer is the one a hand-edited ``.env`` raises —
*is the panel using the file or the database?* — and the answer is not guessable
from the file, because ``URLPATH`` seeds from it once at install and has been a
settings row ever since.

It never writes. That is the whole point: ``.env`` is written once by the
installer and belongs to the operator afterwards, so the only safe way for this
tool to touch it is not to.
"""

from __future__ import annotations

import os

from cli import render
from cli.env import Install

# What .env owns, and why. Ownership is by key name rather than by precedence:
# a key declared here is authoritative, and nothing else declares the same one,
# so there is no ordering to remember and no case where two sources disagree.
BOOT_KEYS = (
    ("DATA_DIR", "found the database with it"),
    ("HOST", "the socket binds before anything is up"),
    ("PORT", "the socket binds before anything is up"),
    ("JWT_SECRET_KEY", "read at startup; rotating it logs everyone out"),
    ("SSL_KEYFILE", "where `ovm tls` puts the key"),
    ("SSL_CERTFILE", "where `ovm tls` puts the certificate"),
    ("PUBLIC_URL", "the address clients are given, behind a proxy"),
    ("ADMIN_USERNAME", "the owner login name"),
)

# The real setting names, not prose. An operator reading this has just come
# from grepping .env, and the next thing they will do is grep for the thing that
# was not in it — so these have to be greppable.
RUNTIME_KEYS = (
    ("urlpath", "panel Settings → General, or `ovm url`"),
    ("owner", "the admins table, or `ovm auth reset`"),
    ("subscription_path", "panel Settings → Advanced"),
    ("trusted_proxy", "panel Settings → Advanced"),
)


def collect(install: Install) -> dict:
    """Read-only. Never raises — an unreadable value is reported, not fatal."""
    env = install.env
    rows = []
    for key, why in BOOT_KEYS:
        value = env.get(key) or os.environ.get(key) or ""
        if key == "JWT_SECRET_KEY":
            value = "set" if value else "unset"
        elif key in ("HOST", "PORT"):
            value = value or "default"
        rows.append((key, value or "unset", ".env", why))
    return {"ok": True, "rows": rows, "install_dir": install.install_dir}


def render_text(data: dict) -> str:
    if not data.get("ok"):
        return render.block([render.failed(data.get("error", "could not read the configuration"))])
    lines = [render.heading("settings")]
    lines.append("")
    width = render.rows_width([(key, "") for key, _, _, _ in data["rows"]])
    for key, value, source, why in data["rows"]:
        lines.append(render.kv(key, value, width))
        lines.append(render.hint(f"{source} — {why}"))
    lines.append("")
    lines.append(render.heading("in the database, not .env"))
    lines += render.rows(RUNTIME_KEYS)
    lines.append("")
    lines.append(render.heading("ownership"))
    lines.append(
        render.hint(
            ".env is written once by the installer and never by this tool — edit it freely, changes take effect on restart"
        )
    )
    lines.append(render.hint("everything not named in .env is a row: change it in the panel"))
    return render.block(lines)
