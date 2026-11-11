# Migrations

One numbered SQL file per schema change after 2.0.0: `NNN_description.sql`.
They run in numeric order and each file commits with its `PRAGMA user_version`
stamp, so a failed file leaves the previous version intact.
