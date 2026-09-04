# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

import os

from cryptography.fernet import Fernet
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


def _validate_fernet_key(v: str) -> str:
    """Validate Fernet key format (32 url-safe base64-encoded bytes)."""
    try:
        Fernet(v.encode())
    except Exception:
        raise ValueError("BOT_ENCRYPT_KEY must be a valid 32-byte URL-safe base64-encoded key") from None
    return v


class Setting(BaseSettings):
    ADMIN_USERNAME: str = Field(min_length=1, max_length=64)
    ADMIN_PASSWORD: str = Field(min_length=12, max_length=256)
    URLPATH: str = ""  # Initial default for DB urlpath; runtime changes via web UI
    HOST: str = "0.0.0.0"
    PORT: int = Field(default=2095, ge=1, le=65535)
    DEBUG: str = "WARNING"
    DOC: bool = False
    SSL_KEYFILE: str | None = None
    SSL_CERTFILE: str | None = None
    # ── Auth: opaque DB-backed sessions (no JWT) ─────────────────────
    # DEPRECATED: panel no longer uses JWT. Kept as an ignored optional field
    # so existing .env files don't fail validation; safe to delete from .env.
    JWT_SECRET_KEY: str | None = None
    # Idle timeout (sliding): session dies after this much inactivity.
    # Absolute cap: a session can never outlive this, no matter the activity.
    # Legacy JWT_* env names are still honoured for a smooth upgrade path.
    SESSION_IDLE_SECONDS: int = Field(
        default=1800,
        ge=60,
        le=86400,
        validation_alias=AliasChoices("SESSION_IDLE_SECONDS", "JWT_ACCESS_TOKEN_EXPIRES"),
    )
    SESSION_MAX_SECONDS: int = Field(
        default=604800,
        ge=600,
        le=7776000,
        validation_alias=AliasChoices("SESSION_MAX_SECONDS", "JWT_REFRESH_TOKEN_EXPIRES"),
    )
    SUBSCRIPTION_URL_PREFIX: str | None = None
    SUBSCRIPTION_PATH: str = Field(default="sub", min_length=1, max_length=64)
    TRUSTED_PROXY: bool = False  # Set true behind nginx/caddy to trust X-Forwarded-For
    # Encryption key for bot token at rest (Fernet)
    BOT_ENCRYPT_KEY: str | None = None
    # Encryption key for node API keys at rest (Fernet). Falls back to
    # BOT_ENCRYPT_KEY when unset so existing installs get encryption
    # without a new secret to manage.
    NODE_ENCRYPT_KEY: str | None = None
    # Installer metadata (ignored by app, used by install.sh for state)
    DATA_DIR: str = ""
    PUBLIC_URL: str | None = None

    model_config = {"env_file": os.path.join(os.path.dirname(__file__), "..", ".env")}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.BOT_ENCRYPT_KEY:
            _validate_fernet_key(self.BOT_ENCRYPT_KEY)
        if self.NODE_ENCRYPT_KEY:
            _validate_fernet_key(self.NODE_ENCRYPT_KEY)
        lowered = (self.ADMIN_PASSWORD or "").lower()
        placeholders = ("change-me", "changeme", "change_me", "password123", "admin123")
        if any(p in lowered for p in placeholders):
            raise ValueError(
                "ADMIN_PASSWORD still looks like a placeholder — set a strong random password in .env "
                "(installer enforces >=8 chars; app requires >=12)"
            )


config = Setting()
