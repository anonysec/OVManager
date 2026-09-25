# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Plain Telegram delivery for verified backup bundles."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import requests

from backend.db import crud
from backend.logger import logger

CHUNK_SIZE = 1024 * 1024
HTTP_TIMEOUT_SECONDS = 120
TELEGRAM_DOCUMENT_TEMPLATE = "https://api.telegram.org/bot{token}/sendDocument"


@dataclass(frozen=True)
class TelegramBackupResult:
    ok: bool
    message_id: int | None = None
    file_id: str | None = None
    size: int = 0
    sha256: str | None = None
    error: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def send_backup_document(backup_path: Path, settings) -> TelegramBackupResult:
    """Send a backup bundle to the configured owner's private chat as-is."""

    if not backup_path.is_file():
        return TelegramBackupResult(False, error="backup file not found")
    owner_id = getattr(settings, "owner_telegram_id", None)
    token = crud.decrypt_bot_token(getattr(settings, "bot_token", None))
    if not owner_id or not token:
        return TelegramBackupResult(False, error="Telegram bot or owner chat is not configured")

    checksum = _sha256(backup_path)
    caption = f"OVManager backup\nSHA256: {checksum}"
    try:
        with backup_path.open("rb") as document:
            response = requests.post(
                TELEGRAM_DOCUMENT_TEMPLATE.format(token=token),
                data={"chat_id": str(owner_id), "caption": caption},
                files={"document": (backup_path.name, document, "application/octet-stream")},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
    except Exception as exc:
        logger.error("Telegram backup upload failed (%s)", type(exc).__name__)
        return TelegramBackupResult(False, error="Telegram upload failed")
    if not response.ok:
        logger.warning("Telegram sendDocument returned HTTP %s", response.status_code)
        return TelegramBackupResult(False, error=f"Telegram HTTP {response.status_code}")
    try:
        result = response.json().get("result", {})
        document_data = result.get("document", {})
        return TelegramBackupResult(
            True,
            message_id=int(result.get("message_id")),
            file_id=document_data.get("file_id"),
            size=backup_path.stat().st_size,
            sha256=checksum,
        )
    except Exception:
        return TelegramBackupResult(False, error="Telegram response was invalid")
