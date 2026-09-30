"""Escaping for user-supplied text that goes into a SQL LIKE.

``%`` and ``_`` are wildcards in LIKE, so interpolating a search term raw lets
the caller widen their own filter: searching for ``%`` matches every row they
can see instead of the literal character. Bound, so not injection, but it makes
the audit filter mean something other than what it says.

Pair every use with ``escape="\\\\"`` on the ``like``/``ilike`` call, or SQLite
has no reason to treat the backslash as an escape character.
"""

from __future__ import annotations

_ESCAPE = "\\"


def escape_like(value: str | None) -> str | None:
    """Escape LIKE metacharacters so ``value`` matches literally.

    Backslash goes first: escaping it after ``%`` would double the backslashes
    this function just inserted, turning ``\\%`` into ``\\\\%`` and matching a
    literal backslash followed by any character.
    """
    if value is None:
        return None
    return value.replace(_ESCAPE, _ESCAPE * 2).replace("%", "\\%").replace("_", "\\_")
