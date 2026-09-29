# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Local operator CLI (read-only commands).

Mirrors the corresponding ``manager.sh`` actions in testable Python; the
mutating flows (install/update/backup/tls/doctor --fix) stay in bash until
their own migration. ``manager.sh`` is untouched — this package is additive.
"""

from __future__ import annotations
