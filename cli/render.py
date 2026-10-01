# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Every character the CLI prints, and the only place it decides any of them.

The installers have this in ``scripts/lib/render.sh``; this is its Python half,
and it exists for the same reason. Seven ``render_text`` functions each built
their own ``f"  {'Label':<14} {value}"`` and their own ``f"  Error: {msg}"``,
which is how the panel ended up with three different indents and a label column
one character too narrow for ``Service account`` — the check most likely to
fail, and the one whose status therefore did not line up.

Layout matches render.sh exactly: three spaces, a 14-wide label field, one
space, then the value. That is not decoration — ``ovm status`` and the install
card land on the same columns, so they read as one product.

No colour. These screens live for about thirty milliseconds, and a fade or a
green tick on something that has already been replaced is noise rather than
signal. What they do carry is the same glyph vocabulary the installers use, so
"done" and "failed" look the same everywhere, and ASCII when the locale cannot
show them.
"""

from __future__ import annotations

import locale
import os

# render.sh's RENDER_LABEL_W. A label wider than this pushes its own value out of
# the column, which is how "Service account" ended up misaligned.
LABEL_W = 14
INDENT = "   "

try:
    _ENCODING = locale.getpreferredencoding(False)
except Exception:  # locale can be unset in a container with no LANG at all
    _ENCODING = "ascii"
_UNICODE = "utf" in _ENCODING.lower()


def glyphs() -> tuple[str, str]:
    """(done, failed) — Unicode where the locale can show it, ASCII where not."""
    return ("✓", "✗") if _UNICODE else ("ok", "XX")


def _unicode_ok() -> bool:
    if _UNICODE:
        return True
    for var in ("LC_ALL", "LC_CTYPE", "LANG"):
        if "utf" in os.environ.get(var, "").lower():
            return True
    return False


def kv(label: str, value: str, width: int | None = None) -> str:
    """One label/value row. The only way a row is ever built.

    `width` defaults to LABEL_W, but callers rendering a known set of rows
    should pass ``rows()``'s computed width instead: a label wider than the
    column pushes its own value out and every row below it misaligns, which is
    how ``Service account`` ended up with its status one column to the right of
    every other check's.
    """
    return f"{INDENT}{label:<{width or LABEL_W}} {value}"


def rows_width(items: list[tuple[str, str]]) -> int:
    """The label column for this exact set of rows, never less than LABEL_W."""
    return max([LABEL_W, *(len(label) for label, _ in items)])


def rows(items: list[tuple[str, str]]) -> list[str]:
    """Every row in a set, sharing one label column."""
    width = rows_width(items)
    return [kv(label, value, width) for label, value in items]


def secret(label: str, value: str, note: str = "", width: int | None = None) -> str:
    """A row whose value is a credential.

    The installers mark these with bold white, which plain text cannot do, so
    the marker moves into the row: the value is followed by what it is and
    whether it is the only copy. That is the information a reader needs before
    they clear the scrollback, and it survives a copy-paste into a ticket.
    """
    return kv(label, f"{value}  {note}".rstrip(), width)


def heading(text: str) -> str:
    return f"  {text}"


def ok(message: str) -> str:
    done, _ = glyphs()
    return f"  {done} {message}"


def failed(message: str) -> str:
    _, bad = glyphs()
    return f"  {bad} {message}"


def hint(message: str) -> str:
    return f"    {message}"


def next_step(command: str, remove: str) -> str:
    """The way out, printed once on failure: how to look, and how to remove."""
    return f"  next  {command} · uninstall: {remove}"


def options(title: str, items: list[tuple[str, str]]) -> str:
    """What a grouped command prints when called bare: the current state, then
    every action it takes. Same rule as ``ovm tls`` and ``ovm auth`` — type the
    command with no arguments and it tells you what it can do."""
    lines = [heading(title), ""] + rows(items)
    return block(lines)


def block(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"
