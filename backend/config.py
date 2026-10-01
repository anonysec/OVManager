import os

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Setting(BaseSettings):
    ADMIN_USERNAME: str = Field(min_length=1, max_length=64)
    # Legacy, read-only: still declared so the v16 migration can import a
    # pre-upgrade hash into the owner row. No authentication path reads these.
    ADMIN_PASSWORD_HASH: str = ""
    ADMIN_PASSWORD: str = ""
    URLPATH: str = ""  # Initial default for DB urlpath; runtime changes via web UI
    HOST: str = "0.0.0.0"
    PORT: int = Field(default=2095, ge=1, le=65535)
    DEBUG: str = "WARNING"
    DOC: bool = False
    SSL_KEYFILE: str | None = None
    SSL_CERTFILE: str | None = None
    JWT_SECRET_KEY: str | None = None
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
    BOT_ENCRYPT_KEY: str | None = None
    NODE_ENCRYPT_KEY: str | None = None
    BACKUP_ENCRYPT_KEY: str | None = None
    DATA_DIR: str = ""
    PUBLIC_URL: str | None = None

    model_config = {"env_file": os.path.join(os.path.dirname(__file__), "..", ".env")}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Credentials live in the database, never here: ADMIN_USERNAME only
        # names the `admins` row that is the owner. A pre-existing
        # ADMIN_PASSWORD_HASH is imported into that row by the v16 migration;
        # ADMIN_PASSWORD is ignored outright — no code path reads it.
        if self.ADMIN_PASSWORD or self.ADMIN_PASSWORD_HASH:
            import logging

            logging.getLogger("config").warning(
                "ADMIN_PASSWORD/ADMIN_PASSWORD_HASH in .env are no longer used — "
                "the owner credential lives in the panel database. "
                "Use `ovm auth reset` to change it; you can delete these lines."
            )


config = Setting()
