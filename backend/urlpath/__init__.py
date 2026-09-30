"""Dynamic URL path prefix (URLPATH) package.

Everything is re-exported from :mod:`backend.urlpath._core`, which holds the
implementation.
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
