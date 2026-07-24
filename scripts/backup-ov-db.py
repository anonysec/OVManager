#!/usr/bin/env python3
"""
Backup script for OVManager SQLite database.
Creates timestamped backups and retains last N backups.
"""
import os
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

# Configuration
DB_PATH = Path("/opt/ovmanager/data/ov-panel.db")
BACKUP_DIR = Path("/opt/ovmanager/backups")
RETENTION_COUNT = 7  # Keep last 7 days


def backup_db():
    """Create a timestamped backup of the database."""
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return False

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"ov-panel-{timestamp}.db"

    # Use SQLite backup API for consistency
    try:
        with sqlite3.connect(str(DB_PATH)) as src:
            with sqlite3.connect(str(backup_path)) as dst:
                src.backup(dst)
        print(f"Backup created: {backup_path}")
    except Exception as e:
        print(f"Backup failed: {e}")
        return False

    # Cleanup old backups
    cleanup_old_backups()
    return True


def cleanup_old_backups():
    """Remove old backups beyond retention count."""
    backups = sorted(BACKUP_DIR.glob("ov-panel-*.db"), reverse=True)
    for old in backups[RETENTION_COUNT:]:
        try:
            old.unlink()
            print(f"Removed old backup: {old}")
        except Exception as e:
            print(f"Failed to remove {old}: {e}")


if __name__ == "__main__":
    backup_db()