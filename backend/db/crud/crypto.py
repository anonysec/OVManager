# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Field encryption for stored secrets (bot tokens, node API keys)."""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from backend.logger import logger

try:
    from backend.config import config as panel_config

    _fernet = Fernet(panel_config.BOT_ENCRYPT_KEY.encode()) if panel_config.BOT_ENCRYPT_KEY else None
    _node_key_raw = panel_config.NODE_ENCRYPT_KEY or panel_config.BOT_ENCRYPT_KEY
    _node_fernet = Fernet(_node_key_raw.encode()) if _node_key_raw else None
except Exception:
    _fernet = None
    _node_fernet = None

if _fernet is None:
    import logging

    logging.getLogger(__name__).warning(
        "BOT_ENCRYPT_KEY not set — bot tokens stored in plaintext at rest. "
        "Set BOT_ENCRYPT_KEY in .env for encryption: "
        'python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
    )

if _node_fernet is None:
    import logging

    logging.getLogger(__name__).warning(
        "NODE_ENCRYPT_KEY (or BOT_ENCRYPT_KEY fallback) not set — node API keys stored in plaintext. "
        "Set NODE_ENCRYPT_KEY in .env for encryption."
    )

def encrypt_node_key(plain: str) -> str:
    """Encrypt a node API key for storage. Prefix marks ciphertext."""
    if _node_fernet is None:
        return plain
    return "enc:" + _node_fernet.encrypt(plain.encode()).decode()


@lru_cache(maxsize=4096)
def decrypt_node_key(stored: str | None) -> str:
    """Decrypt a stored node key; legacy plaintext passes through.

    Pure in (stored, process key) — cached so per-tick fan-outs over N
    nodes don't pay a Fernet decrypt per node per RPC.

    Fail-closed: an ``enc:`` value that cannot be decrypted (wrong or
    rotated key, corrupt row) yields ``""`` instead of leaking the
    ciphertext as a bearer key. Callers then get a clean 401 from the
    node, and the operator knows to re-enter the key.
    """
    if not stored:
        return ""
    if stored.startswith("enc:"):
        if _node_fernet is None:
            logger.error("Node key is encrypted but no NODE/BOT_ENCRYPT_KEY is configured — refusing to use it")
            return ""
        try:
            return _node_fernet.decrypt(stored[4:].encode()).decode()
        except Exception:
            logger.error("Stored node key failed to decrypt (wrong key or corrupt row) — refusing to use it")
            return ""
    return stored


def node_api_key(node) -> str:
    """Plaintext API key for a Node row (decrypts when encrypted)."""
    return decrypt_node_key(getattr(node, "key", ""))

