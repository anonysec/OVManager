# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Dynamic URL path prefix (URLPATH) package.

Same import surface as the old single module — everything is re-exported
from :mod:`backend.urlpath._core`:

    from backend.urlpath import get_urlpath, set_urlpath, URLPathMiddleware
"""

from __future__ import annotations

from backend.urlpath._core import (
    URLPathMiddleware,
    get_urlpath,
    invalidate_cache,
    reserved_prefixes,
    reset_urlpath,
    set_urlpath,
)

__all__ = [
    "URLPathMiddleware",
    "get_urlpath",
    "invalidate_cache",
    "reserved_prefixes",
    "reset_urlpath",
    "set_urlpath",
]
