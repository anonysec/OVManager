#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Part of scripts/lib (the simulated installer repo): sourced by manager.sh,
# mirrored function-for-function inside install.sh (curl-pipe standalone).
# SYNC: tests/test_lib_parity.py enforces the mirror. Pure helpers only.
# Atomic .env read/write.

env_get() {  # env_get FILE KEY → value (empty when missing)
    grep -E "^$2=" "$1" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true
}

env_set() {  # env_set FILE KEY VALUE — rewrite one line, atomically
    local file="$1" key="$2" value="$3" tmp
    tmp="$(mktemp)" || die "Could not stage $file"
    awk -v k="$key" -v v="$value" '
        BEGIN { done = 0 }
        $0 ~ "^" k "=" { if (!done) { print k "=" v; done = 1; next } }
        { print }
        END { if (!done) print k "=" v }
    ' "$file" > "$tmp" || { rm -f "$tmp"; die "Could not update $file"; }
    cat "$tmp" > "$file" || { rm -f "$tmp"; die "Could not update $file"; }
    rm -f "$tmp"
}
