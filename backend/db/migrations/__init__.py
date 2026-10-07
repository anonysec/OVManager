"""Versioned schema migrations for OVManager (SQLite).

Why this exists
---------------
OVManager used to ship an Alembic tree that was never wired up: ``env.py``
imported ``Base`` from a module that did not export it and ``alembic.ini``
used a relative ``script_location``, so ``alembic upgrade head`` failed from
every working directory. The real schema was produced by
``Base.metadata.create_all()`` plus a hand-written ``ALTER TABLE`` allowlist.

``create_all()`` only creates *missing tables* — it never adds a missing
column to a table that already exists. The hand-written allowlist covered six
columns, while the models define many more (``users.uuid``, ``users.node_usage``,
``users.max_logins``, ``admins.telegram_id``, ``admins.username_prefix``, the
``settings.bot_*`` family, …). An existing database created by an older release
therefore silently kept running with columns missing until a query touched one.

This package replaces both with a small, explicit, ordered migration runner:

* The mapped models in ``backend/db/models.py`` are the single source of truth
  for the schema. Columns are reconciled from the metadata, so the adoption
  path cannot drift from the models the way a hardcoded list does.
* Every database carries a ``schema_version`` row, so numbered steps run
  exactly once and in order.
* Existing databases are *adopted*: their current shape is inspected, whatever
  is missing is added, and the database is then stamped at HEAD. No manual
  dump/restore is needed to upgrade an existing install.
* ``verify_schema()`` reports drift instead of letting a half-migrated
  database limp along.

SQLite notes
------------
``ALTER TABLE ... ADD COLUMN`` is used rather than table rebuilds. SQLite
allows ``NOT NULL`` on an added column only when a non-null default is
supplied, so a type-appropriate default is synthesised when the model does not
declare one. Existing rows keep working, and no data is copied.

Layout
------
The runnable parts live in submodules, split by role:

* ``constants`` — ``SCHEMA_VERSION``, the shared lock, extra-table DDL
* ``schema``    — inspection, table creation, column reconciliation
* ``seeds``     — first-run rows (settings, the owner) and the v16 import
* ``steps``     — the numbered steps and the ``STEPS`` table
* ``runner``    — ``migrate()``/``verify_schema()`` and the self-check

This module re-exports every name the old single-file module exposed, public
and private, so ``from backend.db.migrations import X`` keeps working — that
includes the private helpers tests and ``bench/`` reach for directly.
"""

from backend.db.migrations.constants import SCHEMA_VERSION
from backend.db.migrations.runner import migrate, verify_schema
from backend.db.migrations.schema import (
    _add_column_sql,
    _create_extra_tables,
    _create_mapped_tables,
    _reconcile_columns,
    column_names,
    current_version,
    ensure_extra_tables,
    table_names,
)
from backend.db.migrations.seeds import (
    _add_admin_user_defaults,
    _import_owner_credential,
    _seed_owner_and_first_user,
    _seed_settings,
    _seed_summary,
)
from backend.db.migrations.steps import (
    STEPS,
    _add_admin_disabled_flag,
    _add_admin_is_owner,
    _add_auto_backup_settings,
    _add_event_delivered,
    _add_lookup_indices,
    _add_node_server_ca,
    _add_notification_flags,
    _add_notify_node_down,
    _add_offsite_backup_target,
    _add_panel_id,
    _add_telegram_backup_enabled,
    _add_threshold_settings,
    _add_user_tag,
    _cleanup_orphan_daily_rows,
    _decrypt_stored_secrets,
    _encrypt_node_keys,
)

__all__ = [
    "SCHEMA_VERSION",
    "STEPS",
    "_add_admin_disabled_flag",
    "_add_admin_is_owner",
    "_add_admin_user_defaults",
    "_add_auto_backup_settings",
    "_add_column_sql",
    "_add_event_delivered",
    "_add_lookup_indices",
    "_add_node_server_ca",
    "_add_notification_flags",
    "_add_notify_node_down",
    "_add_offsite_backup_target",
    "_add_panel_id",
    "_add_telegram_backup_enabled",
    "_add_threshold_settings",
    "_add_user_tag",
    "_cleanup_orphan_daily_rows",
    "_create_extra_tables",
    "_create_mapped_tables",
    "_decrypt_stored_secrets",
    "_encrypt_node_keys",
    "_import_owner_credential",
    "_reconcile_columns",
    "_seed_owner_and_first_user",
    "_seed_settings",
    "_seed_summary",
    "column_names",
    "current_version",
    "ensure_extra_tables",
    "migrate",
    "table_names",
    "verify_schema",
]
