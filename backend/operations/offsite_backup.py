# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Offsite copy of the newest scheduled backup.

After each scheduled backup the panel can push the fresh ``.db`` file to an
operator-configured remote target using the system ``rsync`` (falling back
to ``scp``). The target is a plain scp-style string: ``[user@]host:/path``.

Design notes
------------
* The transfer runs as a plain ``subprocess.run`` argv list — never through
  a shell — and the target is validated against a strict whitelist pattern
  before it is ever used.
* SSH runs with ``BatchMode=yes`` and a connect timeout so a background job
  can never hang on a password prompt; key-based login is expected.
* Everything is best-effort and never raises: the outcome is returned to
  the caller (the scheduler) which audits and logs it.
* No remote cleanup: the remote side keeps whatever it keeps; the local
  retention policy is unaffected.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from shutil import which

from backend.logger import logger

#: scp/rsync style target: optional user, host (letters/digits/dots/dashes),
#: then an absolute POSIX path. No shell metacharacters survive this pattern.
TARGET_RE = re.compile(r"^([A-Za-z0-9._-]+@)?([A-Za-z0-9._-]+):(/[\w./-]+)$")

#: One transfer attempt must finish within this many seconds.
PUSH_TIMEOUT_SECONDS = 300

_SSH_OPTS = (
    "ssh",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "StrictHostKeyChecking=accept-new",
)


class InvalidTarget(ValueError):
    """Raised when the configured offsite target is not a usable scp-style path."""


def parse_target(target: str | None) -> tuple[str, str, str]:
    """Split ``[user@]host:/path`` into ``(user, host, path)``.

    ``user`` is empty when absent. Raises :class:`InvalidTarget` for
    anything that is not a plain host + absolute path.
    """
    if not target or not (stripped := target.strip()):
        raise InvalidTarget("Offsite backup target is empty")
    match = TARGET_RE.match(stripped)
    if not match:
        raise InvalidTarget(
            "Offsite backup target must look like user@server:/path/to/backups (absolute path, no special characters)"
        )
    user_part = match.group(1)
    return (user_part[:-1] if user_part else "", match.group(2), match.group(3))


def _argv_for(rsync_path: str | None, source: Path, user: str, host: str, dest: str) -> list[str]:
    remote = f"{user}@{host}:{dest}" if user else f"{host}:{dest}"
    if rsync_path:
        return [rsync_path, "-e", " ".join(_SSH_OPTS[1:]), str(source), remote]
    return ["scp", *_SSH_OPTS[1:], str(source), remote]


def push_offsite(backup_path: Path, target: str) -> bool:
    """Push one backup file to the offsite target. Never raises.

    Prefers ``rsync`` (keeps repeated pushes cheap) and falls back to
    ``scp`` when rsync is missing or fails. Returns ``True`` only when the
    remote accepted the file.
    """
    try:
        user, host, dest = parse_target(target)
    except InvalidTarget as exc:
        logger.warning("Offsite backup skipped: %s", exc)
        return False
    if not backup_path.exists():
        logger.warning("Offsite backup skipped: %s does not exist", backup_path.name)
        return False

    dest_with_slash = dest.rstrip("/") + "/"
    rsync_path = which("rsync")
    attempts: list[list[str]] = []
    if rsync_path:
        attempts.append(_argv_for(rsync_path, backup_path, user, host, dest_with_slash))
    attempts.append(_argv_for(None, backup_path, user, host, dest_with_slash))

    last_error = ""
    for argv in attempts:
        tool = argv[0]
        try:
            result = subprocess.run(argv, capture_output=True, timeout=PUSH_TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            logger.error("Offsite backup via %s timed out after %ss", tool, PUSH_TIMEOUT_SECONDS)
            last_error = f"{tool} timed out"
            continue
        except FileNotFoundError:
            last_error = f"{tool} is not installed"
            continue
        if result.returncode == 0:
            logger.info("Offsite backup pushed via %s to %s", tool, host)
            return True
        # stderr may name the remote host — operator data, safe to log;
        # never log full argv (it embeds nothing secret, but stay terse).
        detail = (result.stderr or "").strip().splitlines()
        last_error = f"{tool} exit {result.returncode}: {detail[0][:200]}" if detail else f"{tool} exit {result.returncode}"
        logger.warning("Offsite backup via %s failed: %s", tool, last_error)

    logger.error("Offsite backup failed: %s", last_error)
    return False
