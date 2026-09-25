# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

import os

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Setting(BaseSettings):
    ADMIN_USERNAME: str = Field(min_length=1, max_length=64)
    # Owner credentials: either a bcrypt hash (preferred — the installer and
    # the first-boot migration write ADMIN_PASSWORD_HASH and drop the
    # plaintext) or the legacy plaintext ADMIN_PASSWORD as a fallback.
    ADMIN_PASSWORD: str = ""
    ADMIN_PASSWORD_HASH: str = ""
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
    # Retired in 1.0.5 (secrets are no longer encrypted at rest). Kept as
    # deprecated no-ops so upgrades from key-era installs boot first try:
    # their .env still carries the lines, the old installer stages it
    # verbatim, and unknown keys are rejected at startup. Never read.
    BOT_ENCRYPT_KEY: str | None = None
    NODE_ENCRYPT_KEY: str | None = None
    # Retired in 1.0.3 (backups go plain). Same deprecation pattern.
    BACKUP_ENCRYPT_KEY: str | None = None
    # Installer metadata (ignored by app, used by install.sh for state)
    DATA_DIR: str = ""
    PUBLIC_URL: str | None = None

    model_config = {"env_file": os.path.join(os.path.dirname(__file__), "..", ".env")}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.ADMIN_PASSWORD and not self.ADMIN_PASSWORD_HASH:
            raise ValueError(
                "No owner credentials — set ADMIN_PASSWORD_HASH (bcrypt, preferred) or "
                "ADMIN_PASSWORD in .env"
            )
        if self.ADMIN_PASSWORD_HASH and not self.ADMIN_PASSWORD_HASH.startswith("$2"):
            raise ValueError("ADMIN_PASSWORD_HASH must be a bcrypt hash ($2a/$2b/$2y…)")
        lowered = (self.ADMIN_PASSWORD or "").lower()
        placeholders = ("change-me", "changeme", "change_me", "password123", "admin123")
        if lowered and any(p in lowered for p in placeholders):
            raise ValueError(
                "ADMIN_PASSWORD still looks like a placeholder — set a strong random password in .env "
                "(installer and app require >=8 chars)"
            )


config = Setting()
