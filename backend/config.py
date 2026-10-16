import os
import threading

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Setting(BaseSettings):
    ADMIN_USERNAME: str = Field(min_length=1, max_length=64)
    ADMIN_PASSWORD_HASH: str = ""
    ADMIN_PASSWORD: str = ""
    URLPATH: str = ""  # Initial default for DB urlpath; runtime changes via web UI
    HOST: str = "0.0.0.0"
    PORT: int = Field(default=2095, ge=1, le=65535)
    DEBUG: str = "WARNING"
    DOC: bool = False
    SSL_KEYFILE: str | None = None
    SSL_CERTFILE: str | None = None
    # Allow connecting to a node whose certificate does not verify (self-signed
    # node with no pin). Off by default: the API key must not cross the wire
    # without MITM protection. Set NODE_TLS_INSECURE_FALLBACK=true to opt in.
    NODE_TLS_INSECURE_FALLBACK: bool = False
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
        if self.ADMIN_PASSWORD or self.ADMIN_PASSWORD_HASH:
            import logging

            logging.getLogger("config").warning(
                "ADMIN_PASSWORD/ADMIN_PASSWORD_HASH in .env are no longer used — "
                "the owner credential lives in the panel database. "
                "Use `ovm auth reset` to change it; you can delete these lines."
            )


config = Setting()


class SettingsCache:
    """Process-local cache of the single-row settings table.

    Single worker, so one dict is enough. Writers must replace the entry via
    ``refresh_settings`` (backend.db.crud.settings) after they commit;
    readers never mutate the row.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._row = None

    def get(self):
        with self._lock:
            return self._row

    def set(self, row) -> None:
        with self._lock:
            self._row = row

    def clear(self) -> None:
        with self._lock:
            self._row = None


settings_cache = SettingsCache()


def get_setting(key: str, default=None):
    """Read one setting: settings_kv wins, then the legacy settings column.

    Deferred imports: backend.db.engine imports this module, so the DB stack
    cannot be pulled in at import time. A KV value is returned JSON-decoded
    when it parses ("100" → 100, '{"a": 1}' → dict) and as the raw string
    otherwise. A key that is neither in KV nor a settings column yields
    ``default``.
    """
    import json

    from backend.db.crud.settings import get_cached_settings, get_kv
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        raw = get_kv(db, key)
        if raw is not None:
            try:
                return json.loads(raw)
            except ValueError:
                return raw
        return getattr(get_cached_settings(db), key, default)
    finally:
        db.close()


def low_resource_enabled() -> bool:
    """Is `perf.low_resource` on? Off by default, and off when unsure.

    One flag for the small-box profile: stretched job intervals, a slower live
    poll, a smaller SQLite page cache, no bot spawn for a bot that is not
    configured. ``OVMANAGER_LOW_RESOURCE`` in .env overrides the row so an
    operator can set it before the database exists (and so the suite can run
    the whole profile with one variable). Any database failure reads as off —
    a missing table must never block startup.
    """
    env = os.getenv("OVMANAGER_LOW_RESOURCE", "").strip().lower()
    if env:
        return env in ("1", "true", "yes", "on")
    try:
        raw = get_setting("perf.low_resource", False)
    except Exception:
        return False
    if isinstance(raw, str):  # KV stores text; "false" must not be truthy
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return bool(raw)
