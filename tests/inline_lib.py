"""Cut one helper section out of install.sh's inline block.

These helpers used to be scripts/lib/*.sh, and the probe harnesses in this
suite sourced one or two of them directly so a snippet could exercise
render_menu or ask() without running an installer. They are inline in
install.sh and manager.sh now, and both programs carry byte-identical copies —
so install.sh is the one place to read them from.

A section is located by its banner, the same way install.sh marks it, which
means a renamed or missing section fails here rather than producing a probe that
quietly tests nothing.
"""

from __future__ import annotations

import functools
import os
import re
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "install.sh"

SECTION_NAMES = ("common.sh", "render.sh", "prompt.sh", "env.sh", "system.sh", "backup.sh", "tls.sh", "policy.sh")

_BANNER = re.compile(
    r"^# =+\n# (?P<name>[\w.]+\.sh)\n# =+\n",
    re.M,
)


def _block() -> str:
    lines = INSTALLER.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("# ="))
    end = next(i for i, line in enumerate(lines) if "release_checksum_url() {" in line)
    close = next(i for i in range(end, len(lines)) if lines[i].rstrip() == "}")
    return "".join(lines[start : close + 1])


def block() -> str:
    """The whole inline helper block, exactly as install.sh carries it."""
    return _block()


def section(name: str) -> str:
    """One section's text, banner included, ready to write to a file."""
    if name not in SECTION_NAMES:
        raise AssertionError(f"unknown helper section {name!r}; known: {SECTION_NAMES}")
    matches = list(_BANNER.finditer(_block()))
    for i, m in enumerate(matches):
        if m.group("name") == name:
            stop = matches[i + 1].start() if i + 1 < len(matches) else len(_block())
            return _block()[m.start() : stop]
    raise AssertionError(f"install.sh has no {name} section")


def materialise(names: tuple[str, ...], dest: Path) -> list[Path]:
    """Write the named sections into `dest` and return their paths, in order.

    The order is the caller's and it matters: common.sh sets the colour globals
    and the INT/TERM trap that render.sh reads at source time, and prompt.sh
    calls render_ask(). A probe that sources them out of order tests a shell
    that could never start.
    """
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for name in names:
        path = dest / name
        path.write_text(section(name), encoding="utf-8")
        written.append(path)
    return written


@functools.cache
def path(name: str) -> Path:
    """A stable on-disk copy of one section, written once per test session.

    Most probes want to `.` a real file rather than a string of bash, because
    that is what install.sh does. Cached per process so the file is written once
    and the identity is stable; rewritten from install.sh on every run, so an
    edited installer is picked up rather than served from the last one's temp
    directory.
    """
    dest = Path(tempfile.gettempdir()) / f"ovm-inline-lib-{os.getpid()}"
    return materialise((name,), dest)[0]
