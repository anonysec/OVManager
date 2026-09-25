#!/usr/bin/env python3
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Dump the panel OpenAPI schema to scripts/openapi.json without a server.

Enables offline API-client generation and contract tests. The schema is
gated by config.DOC, so it is forced on here regardless of .env.
"""

from __future__ import annotations

import json
import os
import sys

os.environ["DOC"] = "true"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app import api  # noqa: E402

schema = api.openapi()
out = os.path.join(os.path.dirname(__file__), "openapi.json")
with open(out, "w", encoding="utf-8") as fh:
    json.dump(schema, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
print(f"wrote {out} ({len(schema.get('paths', {}))} paths)")
