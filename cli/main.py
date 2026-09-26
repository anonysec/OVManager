# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Local operator entrypoint: ``python -m cli.main <command>``.

Read-only commands (status/logs/doctor) plus the backup mutating flows
(backup/auto-backup); unknown commands print usage.
"""

from __future__ import annotations

import argparse
import sys

from cli import backup as _backup
from cli import doctor as _doctor
from cli import logs as _logs
from cli import status as _status
from cli.env import Install


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ovm", description="OVManager local operator CLI")
    parser.add_argument("--install-dir", default=None, help="override install dir (default: $OVM_APP_DIR or /opt/ovmanager)")
    parser.add_argument("--data-dir", default=None, help="override data dir")
    parser.add_argument("--json", action="store_true", help="machine-readable output (status)")
    parser.add_argument("-a", "--all", dest="show_all", action="store_true", help="show all fields (status)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="service, health, version, URL")
    logs_p = sub.add_parser("logs", help="tail service logs")
    logs_p.add_argument("count", nargs="?", default="100", help="line count or -f to follow")
    sub.add_parser("doctor", help="read-only health checks")
    backup_p = sub.add_parser("backup", help="save a data backup now")
    backup_p.add_argument("--keep", default=None, help="tarballs to keep (1-500, default 14)")
    auto_p = sub.add_parser("auto-backup", help="panel auto-backup schedule")
    auto_p.add_argument("action", nargs="?", default="status", choices=["status", "on", "off"])
    auto_p.add_argument("--time", default=None, help="daily time HH:MM (for on)")
    auto_p.add_argument("--keep", default=None, help="tarballs to keep 1-500 (for on)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    install = Install.detect(install_dir=args.install_dir, data_dir=args.data_dir)
    if args.command == "status":
        data = _status.collect(install)
        if args.json:
            print(_status.render_json(data))
        else:
            print(_status.render_text(data, show_all=args.show_all), end="")
        return 0 if data.get("ok") else 1
    if args.command == "logs":
        return _logs.run(_logs.build_command(install.install_dir, install.compose_file, args.count))
    if args.command == "doctor":
        checks = _doctor.collect(install)
        print(_doctor.render_text(checks), end="")
        return 0 if all(c.ok for c in checks) else 1
    if args.command == "backup":
        data = _backup.backup_now(install, keep=args.keep)
        if args.json:
            print(_backup.render_backup_json(data))
        else:
            print(_backup.render_backup_text(data), end="")
        return 0 if data.get("ok") else 1
    if args.command == "auto-backup":
        data = _backup.auto_backup(args.action, install, time=args.time, keep=args.keep)
        if args.json:
            print(_backup.render_auto_backup_json(data))
        else:
            print(_backup.render_auto_backup_text(data), end="")
        return 0 if data.get("ok") else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
