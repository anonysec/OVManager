# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Encrypted Telegram delivery for verified backup bundles."""

from __future__ import annotations

import base64
import hashlib
import os
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from backend.db import crud
from backend.logger import logger

MAGIC = b"OVMBENC1"
NONCE_SIZE = 12
TAG_SIZE = 16
CHUNK_SIZE = 1024 * 1024
HTTP_TIMEOUT_SECONDS = 120
TELEGRAM_DOCUMENT_TEMPLATE = "https://api.telegram.org/bot{token}/sendDocument"


@dataclass(frozen=True)
class TelegramBackupResult:
    ok: bool
    message_id: int | None = None
    file_id: str | None = None
    encrypted_size: int = 0
    sha256: str | None = None
    error: str | None = None


def _decode_key(value: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(value.encode())
    except Exception as exc:
        raise ValueError("BACKUP_ENCRYPT_KEY is not valid URL-safe base64") from exc
    if len(key) != 32:
        raise ValueError("BACKUP_ENCRYPT_KEY must encode exactly 32 bytes")
    return key


def encrypt_backup(source: Path, destination: Path, key_value: str) -> tuple[int, str]:
    """Stream-encrypt ``source`` using AES-256-GCM.

    Format: magic, 12-byte nonce, 8-byte plaintext size, ciphertext, 16-byte
    authentication tag. The encrypted artifact is independently checksummed
    for delivery verification and written with private permissions.
    """

    if not source.is_file():
        raise ValueError("backup file does not exist")
    key = _decode_key(key_value)
    nonce = os.urandom(NONCE_SIZE)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    plaintext_size = source.stat().st_size
    digest = hashlib.sha256()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent)
    os.close(fd)
    tmp = Path(raw_tmp)
    os.chmod(tmp, 0o600)
    try:
        with source.open("rb") as src, tmp.open("wb") as dst:
            header = MAGIC + nonce + struct.pack(">Q", plaintext_size)
            dst.write(header)
            digest.update(header)
            for chunk in iter(lambda: src.read(CHUNK_SIZE), b""):
                encrypted = encryptor.update(chunk)
                dst.write(encrypted)
                digest.update(encrypted)
            tail = encryptor.finalize()
            if tail:
                dst.write(tail)
                digest.update(tail)
            dst.write(encryptor.tag)
            digest.update(encryptor.tag)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp, destination)
        os.chmod(destination, 0o600)
        return destination.stat().st_size, digest.hexdigest()
    finally:
        tmp.unlink(missing_ok=True)


def decrypt_backup(source: Path, destination: Path, key_value: str) -> None:
    """Authenticate and decrypt an OVManager encrypted backup artifact."""

    key = _decode_key(key_value)
    total = source.stat().st_size
    minimum = len(MAGIC) + NONCE_SIZE + 8 + TAG_SIZE
    if total < minimum:
        raise ValueError("encrypted backup is truncated")
    with source.open("rb") as src:
        if src.read(len(MAGIC)) != MAGIC:
            raise ValueError("not an OVManager encrypted backup")
        nonce = src.read(NONCE_SIZE)
        expected_size = struct.unpack(">Q", src.read(8))[0]
        src.seek(-TAG_SIZE, os.SEEK_END)
        tag = src.read(TAG_SIZE)
        ciphertext_size = total - minimum
        src.seek(len(MAGIC) + NONCE_SIZE + 8)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        fd, raw_tmp = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent)
        os.close(fd)
        tmp = Path(raw_tmp)
        os.chmod(tmp, 0o600)
        written = 0
        try:
            with tmp.open("wb") as dst:
                remaining = ciphertext_size
                while remaining:
                    chunk = src.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ValueError("encrypted backup is truncated")
                    remaining -= len(chunk)
                    plain = decryptor.update(chunk)
                    dst.write(plain)
                    written += len(plain)
                tail = decryptor.finalize()
                dst.write(tail)
                written += len(tail)
                dst.flush()
                os.fsync(dst.fileno())
            if written != expected_size:
                raise ValueError("encrypted backup size does not match header")
            os.replace(tmp, destination)
            os.chmod(destination, 0o600)
        finally:
            tmp.unlink(missing_ok=True)


def send_backup_document(backup_path: Path, settings, key_value: str) -> TelegramBackupResult:
    """Encrypt and send a backup to the configured owner's private chat."""

    if not backup_path.is_file():
        return TelegramBackupResult(False, error="backup file not found")
    owner_id = getattr(settings, "owner_telegram_id", None)
    token = crud.decrypt_bot_token(getattr(settings, "bot_token", None))
    if not owner_id or not token:
        return TelegramBackupResult(False, error="Telegram bot or owner chat is not configured")

    encrypted = backup_path.with_name(backup_path.name + ".enc")
    try:
        size, checksum = encrypt_backup(backup_path, encrypted, key_value)
        caption = f"OVManager encrypted backup\nSHA256: {checksum}"
        try:
            with encrypted.open("rb") as document:
                response = requests.post(
                    TELEGRAM_DOCUMENT_TEMPLATE.format(token=token),
                    data={"chat_id": str(owner_id), "caption": caption},
                    files={"document": (encrypted.name, document, "application/octet-stream")},
                    timeout=HTTP_TIMEOUT_SECONDS,
                )
        except Exception as exc:
            logger.error("Telegram backup upload failed (%s)", type(exc).__name__)
            return TelegramBackupResult(False, encrypted_size=size, sha256=checksum, error="Telegram upload failed")
        if not response.ok:
            logger.warning("Telegram sendDocument returned HTTP %s", response.status_code)
            return TelegramBackupResult(
                False, encrypted_size=size, sha256=checksum, error=f"Telegram HTTP {response.status_code}"
            )
        try:
            result = response.json().get("result", {})
            document_data = result.get("document", {})
            return TelegramBackupResult(
                True,
                message_id=int(result.get("message_id")),
                file_id=document_data.get("file_id"),
                encrypted_size=size,
                sha256=checksum,
            )
        except Exception:
            return TelegramBackupResult(False, encrypted_size=size, sha256=checksum, error="Telegram response was invalid")
    except Exception as exc:
        logger.error("Telegram backup encryption failed (%s)", type(exc).__name__)
        return TelegramBackupResult(False, error=str(exc))
    finally:
        encrypted.unlink(missing_ok=True)
