# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Panel update checker and one-click updater.

The panel itself never downloads or installs anything: ``/status`` only reads
GitHub's public release API (fail-soft — an unreachable GitHub must never turn
the panel's health page into an error), and ``/run`` hands the work to the
installer that already owns it (``bash /opt/ovmanager/install.sh update``,
detached with ``start_new_session``). Docker installs have no installer inside
the container, so ``/run`` answers with the exact host-side command instead of
pretending it can update itself.
"""

import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests
from fastapi import APIRouter, Depends

from backend.auth.authz import require_owner
from backend.data_paths import DATA_DIR
from backend.operations.audit import log_event
from backend.schema import ResponseModel
from backend.version import __version__

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/updater", tags=["Updater"])

#: Same defaults the installer uses; both are overridable for tests/odd installs.
_DEFAULT_APP_DIR = "/opt/ovmanager"
_DEFAULT_REPO = "anonysec/OVManager"

_HTTP_TIMEOUT = 5.0
_CACHE_TTL = 3600.0
_UPDATE_LOG_NAME = "update.log"

_HOST_COMPOSE_CMD = "docker compose up -d --build"
_HOST_RESTART_CMD = "docker restart ovmanager"

# In-process cache shared by every request; ``ts`` stays 0 until the first check.
_cache: dict = {"ts": 0.0, "latest": None, "source": "unknown", "note": ""}


def _app_dir() -> Path:
    """Installer location (``OVM_APP_DIR`` override mirrors the installer)."""
    return Path(os.environ.get("OVM_APP_DIR") or _DEFAULT_APP_DIR).expanduser()


def _repo() -> str:
    """Upstream repo in ``owner/name`` form (``OVM_REPO`` override)."""
    return (os.environ.get("OVM_REPO") or _DEFAULT_REPO).strip()


def _in_container() -> bool:
    return Path("/.dockerenv").exists()


def _has_systemctl() -> bool:
    return shutil.which("systemctl") is not None


def _version_key(value: str) -> tuple[int, ...]:
    """Semver-ish ordering key: ``"v2.10.1-rc1"`` -> ``(2, 10, 1)``.

    Dependency-free on purpose: the panel only needs to answer "is the latest
    tag newer than ours". Digits must lead the version, so non-version tags
    (``"nightly"``) yield an empty key and never look newer.
    """
    raw = str(value or "").strip().lstrip("vV")
    match = re.match(r"(\d+(?:\.\d+)*)", raw)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _is_newer(latest: str | None, current: str) -> bool:
    if not latest:
        return False
    return _version_key(latest) > _version_key(current)


def _fetch_latest(repo: str) -> tuple[str | None, str, str]:
    """Return ``(tag, source, note)``; never raises.

    Tries ``/releases/latest`` first, then ``/tags`` (repos that tag without
    publishing releases). Any transport error, non-200 or malformed body
    degrades to ``(None, "unknown", note)``.
    """
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"OVManager/{__version__}"}
    api = f"https://api.github.com/repos/{repo}"
    try:
        resp = requests.get(f"{api}/releases/latest", timeout=_HTTP_TIMEOUT, headers=headers)
        if resp.status_code == 200:
            tag = (resp.json() or {}).get("tag_name")
            if tag:
                return str(tag).strip(), "github", ""

        resp = requests.get(f"{api}/tags", timeout=_HTTP_TIMEOUT, headers=headers)
        if resp.status_code == 200:
            tags = resp.json() or []
            if isinstance(tags, list) and tags:
                name = (tags[0] or {}).get("name")
                if name:
                    return str(name).strip(), "github", ""

        return None, "unknown", "GitHub did not report any release or tag."
    except Exception as exc:
        logger.info("Update check failed for %s: %s", repo, exc)
        return None, "unknown", "Could not reach GitHub (network error or rate limit)."


def _latest_cached(repo: str) -> tuple[str | None, str, str, int]:
    """Fetch (or serve from the 1-hour cache) the latest tag plus its checked-at time."""
    now = time.time()
    cached_at = float(_cache.get("ts") or 0.0)
    if cached_at and (now - cached_at) < _CACHE_TTL:
        return (
            _cache.get("latest"),
            str(_cache.get("source") or "unknown"),
            str(_cache.get("note") or ""),
            int(cached_at),
        )
    latest, source, note = _fetch_latest(repo)
    _cache.update({"ts": now, "latest": latest, "source": source, "note": note})
    return latest, source, note, int(now)


@router.get("/status", response_model=ResponseModel)
def update_status(user: dict = Depends(require_owner)):
    """Check the latest upstream tag. Fail-soft: success is always true."""
    latest, source, note, checked_at = _latest_cached(_repo())
    data = {
        "current": __version__,
        "latest": latest,
        "update_available": _is_newer(latest, __version__),
        "source": source,
        "checked_at": checked_at,
    }
    if note:
        data["note"] = note
    return ResponseModel(success=True, msg=note or "Update status", data=data)


@router.get("/operation", response_model=ResponseModel)
def update_operation(user: dict = Depends(require_owner)):
    """Return the persisted host-side update transaction state."""
    state_path = DATA_DIR / "update-state.json"
    if not state_path.is_file():
        return ResponseModel(success=True, msg="No update transaction recorded", data=None)
    try:
        import json

        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ResponseModel(success=False, msg="The update state file is unreadable", data=None)
    allowed = {key: data.get(key) for key in ("phase", "from_version", "to_version", "safety_backup", "updated_at", "pid")}
    allowed["maintenance"] = (DATA_DIR / "update-maintenance").is_file()
    allowed["finished"] = data.get("phase") in {"committed", "failed_over"}
    return ResponseModel(success=True, msg="Update transaction state", data=allowed)


def _start_native_update(install_sh: Path, user: dict) -> ResponseModel:
    """Detach ``bash <install_sh> update`` and return immediately."""
    log_path = DATA_DIR / _UPDATE_LOG_NAME
    argv = ["bash", str(install_sh), "update"]
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab") as log_file:
            subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        logger.exception("Could not start the OVManager updater")
        return ResponseModel(success=False, msg=f"Could not start the updater: {exc}", data=None)

    log_event(
        None,
        "panel.update",
        actor=user.get("username"),
        detail=f"started from version {__version__}; log: {log_path}",
    )
    return ResponseModel(
        success=True,
        msg="Update started. The panel will restart in a moment.",
        data={
            "command": f"bash {install_sh} update",
            "log": str(log_path),
            "previous_version": __version__,
        },
    )


@router.post("/run", response_model=ResponseModel)
def run_update(user: dict = Depends(require_owner)):
    """Start the installer in the background, or explain the host-side command."""
    install_sh = _app_dir() / "install.sh"
    in_container = _in_container()
    if not in_container and install_sh.is_file() and _has_systemctl():
        return _start_native_update(install_sh, user)

    if in_container:
        reason = "The panel is running inside a container, so it cannot update itself."
    elif not install_sh.is_file():
        reason = f"The installer was not found at {install_sh}."
    else:
        reason = "systemctl was not found, so the service cannot be restarted automatically."
    return ResponseModel(
        success=False,
        msg=f"{reason} From the host, run: {_HOST_COMPOSE_CMD} (or {_HOST_RESTART_CMD}).",
        data={
            "mode": "docker" if in_container else "manual",
            "command": _HOST_COMPOSE_CMD,
            "restart_command": _HOST_RESTART_CMD,
        },
    )
