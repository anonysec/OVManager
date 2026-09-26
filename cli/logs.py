# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm logs` in Python: docker logs or journalctl, same selection rules."""

from __future__ import annotations

import os
import subprocess

VALID_N = 100


def build_command(install_dir: str, compose_file: str, arg: str = "100") -> list[str]:
    """Return the argv to run (tests assert selection, never execute)."""
    if os.path.isfile(compose_file):
        if arg == "-f":
            return ["docker", "logs", "-f", "--tail", "100", "ovmanager"]
        return ["docker", "logs", "--tail", arg, "ovmanager"]
    if arg == "-f":
        return ["journalctl", "-u", "ovmanager.service", "-n", "100", "-f"]
    return ["journalctl", "-u", "ovmanager.service", "-n", arg, "--no-pager"]


def run(argv: list[str]) -> int:
    try:
        completed = subprocess.run(argv)
        return completed.returncode
    except Exception as exc:
        print(f"  Could not read logs: {exc}")
        return 1
