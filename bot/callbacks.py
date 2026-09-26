"""Typed callback registry for inline-button actions.

Replaces the linear prefix if-chain: each ``prefix:`` maps to exactly one
handler. ``build_callback`` guards Telegram's 64-byte ``callback_data``
limit at construction time instead of failing silently at send time.
``*_arg`` helpers validate the argument half in one place so handlers
never slice raw indexes or int() untrusted strings directly.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

MAX_CALLBACK_BYTES = 64

# Panel UUIDs are uuid4 hex; be lenient (test doubles use short ids) but
# reject anything that could smuggle a second callback inside.
_UUID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def build_callback(prefix: str, arg: str | int) -> str:
    """Build ``"<prefix>:<arg>"`` callback data, enforcing the size limit."""
    data = f"{prefix}:{arg}"
    if len(data.encode()) > MAX_CALLBACK_BYTES:
        raise ValueError(f"callback data exceeds {MAX_CALLBACK_BYTES} bytes: {prefix}:…")
    return data


def uuid_arg(arg: str) -> str | None:
    """Validate a user-uuid argument; None means malformed (fail closed)."""
    arg = (arg or "").strip()
    return arg if _UUID_RE.fullmatch(arg) else None


def int_arg(arg: str, default: int = 0) -> int:
    """Parse an integer argument; the default on anything unparseable."""
    try:
        return int(str(arg).strip())
    except (TypeError, ValueError):
        return default


def node_ref_arg(arg: str) -> tuple[str, int] | None:
    """Parse ``"<uuid>:<node_id>"`` (the dl: download reference)."""
    uuid, sep, node_id_s = (arg or "").rpartition(":")
    if not sep:
        return None
    uuid = uuid_arg(uuid)
    if uuid is None:
        return None
    try:
        return uuid, int(node_id_s)
    except (TypeError, ValueError):
        return None


ActionHandler = Callable[..., Awaitable[bool]]

_registry: list[tuple[str, ActionHandler, dict]] = []


def action(prefix: str, **kwargs):
    """Register a handler for ``"<prefix>:<arg>"`` callbacks."""

    def decorator(fn: ActionHandler) -> ActionHandler:
        _registry.append((prefix, fn, kwargs))
        return fn

    return decorator


def parse_callback(data: str) -> tuple[ActionHandler | None, dict | None, str]:
    """Match ``data`` against the registry in registration order.

    Returns ``(handler, kwargs, arg)`` or ``(None, None, data)`` when no
    prefix matches (the caller falls through to the next dispatcher).
    """
    for prefix, fn, kwargs in _registry:
        if data.startswith(prefix + ":"):
            return fn, kwargs, data[len(prefix) + 1 :]
    return None, None, data
