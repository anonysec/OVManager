#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Part of scripts/lib: sourced by manager.sh, and fetched and sourced by
# install.sh at startup (curl-pipe standalone). One definition per helper —
# tests/test_lib_sourcing.py enforces that.
#
# Colour globals and the fatal-exit path. Rendering lives in render.sh; this
# file owns what it needs to render at all, and the one thing rendering must
# not own — the exit.

# ── Colour / TTY ───────────────────────────────────────────────────────
NC=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'
WH=$'\033[97m'; GR=$'\033[32m'; RD=$'\033[31m'
YL=$'\033[33m'; CY=$'\033[36m'; GY=$'\033[90m'
OR=$'\033[38;5;208m'
# Colour only when stderr is a terminal. Every helper in this library writes to
# fd 2, so the gate must test fd 2: [[ -t 1 ]] passed on `2>install.log` from a
# terminal and wrote escape codes into the log, and failed on `>/dev/null` and
# stripped colour from a terminal that could show it. The node side already uses
# [[ -t 2 ]] — this matches it.
# TERM=dumb is in the same condition as NO_COLOR and not a colour: a dumb
# terminal honours no escapes at all, and writing them produces the visible
# garbage the mode exists to prevent.
[[ -t 2 && -z "${NO_COLOR:-}" && "${TERM:-dumb}" != "dumb" ]] \
    || { NC=''; B=''; D=''; WH=''; GR=''; RD=''; YL=''; CY=''; GY=''; OR=''; }

trap 'printf "\n  %bInterrupted.%b\n" "$RD" "$NC" >&2; exit 130' INT TERM

# Fatal exit. Deliberately NOT a render helper: this is the exit path, not
# decoration, and it must keep working when the terminal is unusable, when
# render.sh failed to source, and when output is a pipe. The Run ID is the
# support handle — it ties a log, a backup file and an update journal together.
die() {
    local run_id="${OVM_RUN_ID:-$(date +%Y%m%d-%H%M%S)-$$}"
    printf '\n  %bError:%b %s\n  %bRun ID:%b %s\n\n' "$RD" "$NC" "$1" "$GY" "$NC" "$run_id" >&2
    exit 1
}

is_port() { [[ "$1" =~ ^[0-9]+$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )); }

rand_path() {
    openssl rand -hex 4 2>/dev/null || head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

rand_pass() {
    openssl rand -base64 12 2>/dev/null | tr -d '/+=\n' | head -c 12
}

rand_hex() {
    openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
}
