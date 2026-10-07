"""The numbered migration steps, in order, and the STEPS table."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import models as _models  # noqa: F401
from backend.db.engine import Base
from backend.db.migrations.schema import (
    _add_column_sql,
    column_names,
    table_names,
)
from backend.db.migrations.seeds import (
    _add_admin_user_defaults,
    _import_owner_credential,
    _seed_owner_and_first_user,
)
from backend.logger import logger


def _encrypt_node_keys(db: Session) -> None:
    """Retired no-op (was: encrypt node API keys at rest, v2).

    At-rest encryption is gone: the DB file behind 0600 perms on an owner-held
    server is the trust boundary. Databases stamped below v2 pass through.
    """
    logger.info("migrations v2: at-rest key encryption is retired — no-op")


def _decrypt_stored_secrets(db: Session) -> None:
    """Decrypt ``enc:`` rows once (v14): at-rest encryption is retired.

    Reads the retired ``BOT/NODE_ENCRYPT_KEY`` values still present in .env on
    the first boot after the upgrade. Rows that fail to decrypt are left
    untouched and reported — fail-closed, never truncated. A no-op when the
    values are absent (fresh installs, already-plaintext databases).
    """
    from cryptography.fernet import Fernet

    from backend.config import config

    bot_fernet = None
    if config.BOT_ENCRYPT_KEY:
        try:
            bot_fernet = Fernet(config.BOT_ENCRYPT_KEY.encode())
        except Exception:
            logger.warning("migrations v14: BOT_ENCRYPT_KEY is not a valid key — legacy token left as-is")
    if bot_fernet:
        row = db.execute(text("SELECT bot_token FROM settings LIMIT 1")).fetchone()
        stored = (row[0] if row else None) or ""
        if stored.startswith("enc:"):
            try:
                plain = bot_fernet.decrypt(stored[4:].encode()).decode()
                db.execute(text("UPDATE settings SET bot_token = :t"), {"t": plain})
                logger.info("migrations v14: decrypted stored bot token")
            except Exception:
                logger.warning(
                    "migrations v14: stored bot token could not be decrypted — leaving as-is; "
                    "re-save the token in Settings → Bot to clear it"
                )

    node_fernet = None
    raw_node_key = config.NODE_ENCRYPT_KEY or config.BOT_ENCRYPT_KEY
    if raw_node_key:
        try:
            node_fernet = Fernet(raw_node_key.encode())
        except Exception:
            logger.warning("migrations v14: node key value is not a valid Fernet key — legacy keys left as-is")
    if node_fernet:
        rows = db.execute(text("SELECT id, key FROM nodes")).fetchall()
        decrypted = 0
        for node_id, stored in rows:
            if not stored or not str(stored).startswith("enc:"):
                continue
            try:
                plain = node_fernet.decrypt(str(stored)[4:].encode()).decode()
                db.execute(text("UPDATE nodes SET key = :k WHERE id = :i"), {"k": plain, "i": node_id})
                decrypted += 1
            except Exception:
                logger.warning(
                    "migrations v14: node %s key could not be decrypted — left as-is; re-enter the key",
                    node_id,
                )
        if decrypted:
            logger.info("migrations v14: decrypted %s node key(s)", decrypted)


def _add_node_server_ca(db: Session) -> None:
    """Add ``nodes.server_ca`` (v15): TLS-pinned node certificates.

    The panel stores the node's certificate (PEM) and verifies HTTPS against
    it, so a self-signed node is as safe as an LE one — no unverified
    fallback. Guarded so adoption (before==0) never re-adds the column.
    """
    if "nodes" not in table_names(db) or "server_ca" in column_names(db, "nodes"):
        return
    column = Base.metadata.tables["nodes"].columns["server_ca"]
    db.execute(text(_add_column_sql("nodes", column)))


def _cleanup_orphan_daily_rows(db: Session) -> None:
    """Delete per-day history rows whose user no longer exists.

    SQLite reuses auto-increment ids, so a deleted user's orphaned rows would
    otherwise surface under the next user that inherits the id.
    """
    if "user_traffic_daily" not in table_names(db):
        return
    result = db.execute(text("DELETE FROM user_traffic_daily WHERE user_id NOT IN (SELECT id FROM users)"))
    logger.info("migrations v3: removed %s orphan daily traffic row(s)", result.rowcount or 0)


def _add_lookup_indices(db: Session) -> None:
    """Add indices for columns the scheduler filters on every tick (v4)."""
    statements = (
        "CREATE INDEX IF NOT EXISTS idx_users_owner ON users(owner)",
        "CREATE INDEX IF NOT EXISTS idx_users_expiry ON users(expiry_date)",
        "CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status)",
        "CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name)",
    )
    for statement in statements:
        db.execute(text(statement))


def _add_admin_disabled_flag(db: Session) -> None:
    """Add ``admins.disabled`` for databases stamped before v5.

    Reconciliation runs only when adopting a pre-runner database, so a database
    stamped at 4 has the table but not the column.
    """
    if "admins" not in table_names(db) or "disabled" in column_names(db, "admins"):
        return
    column = Base.metadata.tables["admins"].columns["disabled"]
    db.execute(text(_add_column_sql("admins", column)))


def _add_notification_flags(db: Session) -> None:
    """Add ``settings.notify_expiry`` / ``settings.notify_traffic`` (v6).

    Both default to True, so existing installs keep sending the daily Telegram
    alerts. Reconciliation runs only when adopting a pre-runner database, so a
    database stamped at 5 needs this.
    """
    if "settings" not in table_names(db):
        return
    present = column_names(db, "settings")
    for name in ("notify_expiry", "notify_traffic"):
        if name in present:
            continue
        column = Base.metadata.tables["settings"].columns[name]
        db.execute(text(_add_column_sql("settings", column)))


def _add_auto_backup_settings(db: Session) -> None:
    """Add ``settings.auto_backup_*`` for databases stamped before v7.

    Auto backup is off by default, so existing installs keep behaving as before.
    Reconciliation runs only when adopting a pre-runner database, so a database
    stamped at 6 needs this.
    """
    if "settings" not in table_names(db):
        return
    present = column_names(db, "settings")
    for name in ("auto_backup_enabled", "auto_backup_time", "auto_backup_keep"):
        if name in present:
            continue
        column = Base.metadata.tables["settings"].columns[name]
        db.execute(text(_add_column_sql("settings", column)))


def _add_user_tag(db: Session) -> None:
    """Add ``users.tag`` for databases stamped before v8.

    Reconciliation covers pre-runner databases only; versioned ones need this.
    """
    if "users" not in table_names(db) or "tag" in column_names(db, "users"):
        return
    column = Base.metadata.tables["users"].columns["tag"]
    db.execute(text(_add_column_sql("users", column)))


def _add_notify_node_down(db: Session) -> None:
    """Add ``settings.notify_node_down`` for databases stamped before v9."""
    if "settings" not in table_names(db) or "notify_node_down" in column_names(db, "settings"):
        return
    column = Base.metadata.tables["settings"].columns["notify_node_down"]
    db.execute(text(_add_column_sql("settings", column)))


def _add_offsite_backup_target(db: Session) -> None:
    """Add ``settings.offsite_backup_target`` for databases stamped before v10."""
    if "settings" not in table_names(db) or "offsite_backup_target" in column_names(db, "settings"):
        return
    column = Base.metadata.tables["settings"].columns["offsite_backup_target"]
    db.execute(text(_add_column_sql("settings", column)))


def _add_telegram_backup_enabled(db: Session) -> None:
    """Add the opt-in encrypted Telegram backup switch (v11)."""
    if "settings" not in table_names(db) or "telegram_backup_enabled" in column_names(db, "settings"):
        return
    column = Base.metadata.tables["settings"].columns["telegram_backup_enabled"]
    db.execute(text(_add_column_sql("settings", column)))


def _add_tls_and_setup_settings(db: Session) -> None:
    """Add the TLS/ACME and Telegram-wizard columns (v17).

    DB is canonical for TLS settings; ``.env`` overrides a field only when the
    operator uncomments it. The wizard flags share the row so the bot has one
    place to read setup state from.
    """
    if "settings" not in table_names(db):
        return
    present = column_names(db, "settings")
    columns = (
        "ssl_cert_file",
        "ssl_key_file",
        "acme_domain",
        "acme_email",
        "cert_method",
        "panel_url",
        "bot_owner_setup_complete",
    )
    for name in columns:
        if name in present:
            continue
        column = Base.metadata.tables["settings"].columns[name]
        db.execute(text(_add_column_sql("settings", column)))


def _add_panel_domain(db: Session) -> None:
    """Add ``settings.panel_domain`` (v18): the domain used in generated .ovpn files."""
    if "settings" not in table_names(db) or "panel_domain" in column_names(db, "settings"):
        return
    column = Base.metadata.tables["settings"].columns["panel_domain"]
    db.execute(text(_add_column_sql("settings", column)))


def _add_threshold_settings(db: Session) -> None:
    """Add the threshold-alert settings (v19): days-left, usage %, CPU %.

    Node-down and expiry already have their toggles (``notify_node_down``,
    ``notify_expiry``); only the numbers and the two new event switches are
    missing. Existing rows get the model defaults, so an upgrade keeps the
    documented 3 days / 80% / 85% behaviour.
    """
    if "settings" not in table_names(db):
        return
    present = column_names(db, "settings")
    for name in ("alert_days_left", "alert_usage_enabled", "alert_usage_pct", "alert_cpu_enabled", "alert_cpu_pct"):
        if name in present:
            continue
        column = Base.metadata.tables["settings"].columns[name]
        db.execute(text(_add_column_sql("settings", column)))


def _add_subscription_profile_settings(db: Session) -> None:
    """Add the subscription-page profile columns (v20): title, support, announce, refresh.

    The customer-facing subscription page is OpenVPN-only, so these shape the
    page itself rather than any client format. Defaults: branded page title,
    no support link, no announcement banner, 12h refresh.
    """
    if "settings" not in table_names(db):
        return
    present = column_names(db, "settings")
    for name in ("sub_profile_title", "sub_support_url", "sub_announce", "sub_update_interval_hours"):
        if name in present:
            continue
        column = Base.metadata.tables["settings"].columns[name]
        db.execute(text(_add_column_sql("settings", column)))


STEPS: tuple[tuple[int, str, object], ...] = (
    (2, "encrypt node API keys at rest", _encrypt_node_keys),
    (3, "drop orphan daily traffic rows", _cleanup_orphan_daily_rows),
    (4, "add lookup indices", _add_lookup_indices),
    (5, "add admin disabled flag", _add_admin_disabled_flag),
    (6, "add Telegram notification flags", _add_notification_flags),
    (7, "add automatic backup settings", _add_auto_backup_settings),
    (8, "add user tag column", _add_user_tag),
    (9, "add node-down alert flag", _add_notify_node_down),
    (10, "add offsite backup target", _add_offsite_backup_target),
    (11, "add encrypted Telegram backup setting", _add_telegram_backup_enabled),
    (12, "seed owner row and first user", _seed_owner_and_first_user),
    (13, "add per-admin user defaults", _add_admin_user_defaults),
    (14, "decrypt stored secrets (at-rest encryption retired)", _decrypt_stored_secrets),
    (15, "add node server_ca (TLS pinning)", _add_node_server_ca),
    (16, "move the owner credential into the database", _import_owner_credential),
    (17, "add TLS/ACME and Telegram wizard settings", _add_tls_and_setup_settings),
    (18, "add panel domain setting", _add_panel_domain),
    (19, "add threshold alert settings", _add_threshold_settings),
    (20, "add subscription profile settings", _add_subscription_profile_settings),
)
