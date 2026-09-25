# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Conversation-flow helpers: one dict in ``context.user_data["flow"]``.

Replaces ad-hoc ``user_data.get("flow")`` / ``["flow"] = {...}`` /
``.pop("flow")`` touches scattered across the handlers. A flow is always
a dict with at least ``kind``; anything else is treated as absent.
"""

from __future__ import annotations

from telegram.ext import ContextTypes

_FLOW_KEY = "flow"


def get_flow(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    """Return the active flow dict, or None when absent/corrupt."""
    flow = context.user_data.get(_FLOW_KEY)
    if not isinstance(flow, dict) or "kind" not in flow:
        return None
    return flow


def set_flow(context: ContextTypes.DEFAULT_TYPE, kind: str, **kwargs) -> dict:
    """Start (or replace) a flow; returns it for further mutation."""
    flow = {"kind": kind, **kwargs}
    context.user_data[_FLOW_KEY] = flow
    return flow


def clear_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Drop any active flow (menu navigation, cancel, completion)."""
    context.user_data.pop(_FLOW_KEY, None)
