"""Typed callback registry for inline-button actions.

Replaces the linear prefix if-chain: each ``prefix:`` maps to exactly one
handler. ``build_callback`` guards Telegram's 64-byte ``callback_data``
limit at construction time instead of failing silently at send time.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

MAX_CALLBACK_BYTES = 64


def build_callback(prefix: str, arg: str | int) -> str:
    """Build ``"<prefix>:<arg>"`` callback data, enforcing the size limit."""
    data = f"{prefix}:{arg}"
    if len(data.encode()) > MAX_CALLBACK_BYTES:
        raise ValueError(f"callback data exceeds {MAX_CALLBACK_BYTES} bytes: {prefix}:…")
    return data


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
