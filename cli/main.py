# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Local operator entrypoint: ``python -m cli.main <command>``.

Read-only commands (status/logs/doctor) plus mutating flows
(backup/auto-backup, reset-password, reset-urlpath); unknown commands
print usage.
"""

from __future__ import annotations

import argparse
import os
import sys

from cli import backup as _backup
from cli import config as _config
from cli import doctor as _doctor
from cli import logs as _logs
from cli import password as _password
from cli import restore as _restore
from cli import status as _status
from cli import tls as _tls
from cli import urlpath as _urlpath
from cli.env import Install


def _global_flags(parser: argparse.ArgumentParser, *, copy: bool = False) -> argparse.ArgumentParser:
    """Global flags, accepted before *or* after the subcommand.

    `ovm status --all` has to work as well as `ovm --all status`. The subparser
    copies suppress their defaults: argparse would otherwise overwrite the
    value the main parser already stored (a shared parent parser re-declares
    every action, and the subparser's default wins).
    """
    unset: object = argparse.SUPPRESS if copy else None
    parser.add_argument(
        "--install-dir",
        default=unset,
        help="override install dir (default: $OVM_APP_DIR or /opt/ovmanager)",
    )
    parser.add_argument("--data-dir", default=unset, help="override data dir")
    # Set by manager.sh when it runs the CLI *inside* the panel container: the
    # host .env is passed in as environment variables rather than mounted, and
    # there is no docker CLI in there to ask about the service.
    parser.add_argument(
        "--in-container",
        action="store_true",
        default=argparse.SUPPRESS if copy else False,
        help="running inside the panel container (set by ovm)",
    )
    parser.add_argument(
        "--service-state",
        default=argparse.SUPPRESS if copy else None,
        help="service state reported by the host (running/stopped/unknown)",
    )
    parser.add_argument(
        "--public-ip",
        default=argparse.SUPPRESS if copy else None,
        help="the host's primary IP (a container only knows its own)",
    )
    if copy:
        parser.add_argument(
            "-a",
            "--all",
            dest="show_all",
            action="store_true",
            default=argparse.SUPPRESS,
            help="show all fields (status)",
        )
    else:
        parser.add_argument("-a", "--all", dest="show_all", action="store_true", default=False, help="show all fields (status)")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = _global_flags(argparse.ArgumentParser(prog="ovm", description="OVManager local operator CLI"))
    common = _global_flags(argparse.ArgumentParser(add_help=False), copy=True)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("status", "service, health, version, URL"),
        ("doctor", "read-only health checks"),
        ("tls-status", "installed certificate at a glance"),
        ("reset-urlpath", "clear the panel URL prefix"),
        ("urlpath-show", "print the url prefix the panel is serving"),
        ("config", "print every effective setting and where it comes from"),
        ("tls-migrate", "move a pre-declaration certificate onto the .env paths"),
    ):
        sub.add_parser(name, help=help_text, parents=[common])
    logs_p = sub.add_parser("logs", help="tail service logs", parents=[common])
    logs_p.add_argument("count", nargs="?", default="100", help="line count or -f to follow")
    doc_fix = sub.add_parser("doctor-fix", help="health checks + auto-fix service/autostart/perms", parents=[common])
    doc_fix.set_defaults(command="doctor-fix")
    backup_p = sub.add_parser("backup", help="save a data backup now", parents=[common])
    backup_p.add_argument("--keep", default=None, help="tarballs to keep (1-500, default 14)")
    auto_p = sub.add_parser("auto-backup", help="panel auto-backup schedule", parents=[common])
    auto_p.add_argument("action", nargs="?", default="status", choices=["status", "on", "off"])
    auto_p.add_argument("--time", default=None, help="daily time HH:MM (for on)")
    auto_p.add_argument("--keep", default=None, help="tarballs to keep 1-500 (for on)")
    restore_p = sub.add_parser("restore", help="list backups, or restore one by name", parents=[common])
    restore_p.add_argument("name", nargs="?", default=None, help="backup filename, as listed")
    ups = sub.add_parser("urlpath-set", help="set the url prefix", parents=[common])
    ups.add_argument("prefix", nargs="?", default="", help="prefix, or empty for the root")
    rp = sub.add_parser("reset-password", help="rewrite the owner credential (hashed)", parents=[common])
    rp.add_argument("--admin-pass", default=None, help="new password (else prompt)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    install = Install.detect(install_dir=args.install_dir, data_dir=args.data_dir)
    # Host facts manager.sh can see and we cannot (no docker CLI in here).
    service = getattr(args, "service_state", None)
    in_container = getattr(args, "in_container", False)
    public_ip = getattr(args, "public_ip", None)
    if args.command == "status":
        data = _status.collect(install, service, public_ip)
        print(_status.render_text(data, show_all=args.show_all), end="")
        return 0 if data.get("ok") else 1
    if args.command == "logs":
        return _logs.run(_logs.build_command(install.install_dir, install.compose_file, args.count))
    if args.command == "doctor":
        checks = _doctor.collect(install, service, in_container)
        print(_doctor.render_text(checks, show_all=args.show_all), end="")
        return 0 if all(c.ok for c in checks) else 1
    if args.command == "doctor-fix":
        checks = _doctor.fix_all(install, service, in_container)
        print(_doctor.render_text(checks, show_all=args.show_all), end="")
        return 0 if all(c.ok for c in checks) else 1
    if args.command == "tls-status":
        data = _tls.status(install)
        print(_tls.render_text(data), end="")
        return 0
    if args.command == "backup":
        data = _backup.backup_now(install, keep=args.keep)
        print(_backup.render_backup_text(data), end="")
        return 0 if data.get("ok") else 1
    if args.command == "auto-backup":
        data = _backup.auto_backup(args.action, install, time=args.time, keep=args.keep)
        print(_backup.render_auto_backup_text(data), end="")
        return 0 if data.get("ok") else 1
    if args.command == "restore":
        # No name is the listing: it reports what is available and changes
        # nothing, so the operator can pick one.
        if not args.name:
            data = _restore.list_backups(install)
            print(_restore.render_list_text(data), end="")
            return 0 if data.get("ok") else 1
        data = _restore.restore_backup(install, args.name)
        print(_restore.render_restore_text(data), end="")
        return 0 if data.get("ok") else 1
    if args.command == "reset-password":
        # Flag, then environment (how the manager passes it, to keep the secret
        # out of `ps` output), then an interactive prompt.
        password = args.admin_pass or os.environ.get("OVM_ADMIN_PASS")
        if not password:
            import getpass

            try:
                password = getpass.getpass("  New password: ")
            except (EOFError, KeyboardInterrupt):
                return 2
        data = _password.reset_password(install.install_dir, password, install.data_dir)
        print(_password.render_text(data), end="")
        return 0 if data.get("ok") else 1
    if args.command == "reset-urlpath":
        data = _urlpath.reset(install.install_dir, install.compose_file, in_container=in_container)
        print(_urlpath.render_text(data), end="")
        return 0 if data.get("ok") else 1
    if args.command == "urlpath-show":
        data = _urlpath.current()
        print(_urlpath.render_current(data), end="")
        return 0 if data.get("ok") else 1
    if args.command == "urlpath-set":
        data = _urlpath.set_prefix(args.prefix or "")
        print(_urlpath.render_set(data), end="")
        return 0 if data.get("ok") else 1
    if args.command == "config":
        data = _config.collect(install)
        print(_config.render_text(data), end="")
        return 0 if data.get("ok") else 1
    if args.command == "tls-migrate":
        data = _tls.migrate()
        # Silent when there is nothing to do: this runs before every `ovm tls`,
        # and a line saying "nothing happened" on every read is noise.
        print(_tls.render_migrate(data), end="")
        return 0 if data.get("ok") else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
