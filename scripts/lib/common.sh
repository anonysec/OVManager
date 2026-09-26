#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Part of scripts/lib (the simulated installer repo): sourced by manager.sh,
# mirrored function-for-function inside install.sh (curl-pipe standalone).
# SYNC: tests/test_lib_parity.py enforces the mirror. Pure helpers only.
# Colour, exit, randomness (sourced first).

# ── Colour / TTY ───────────────────────────────────────────────────────
NC=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'
WH=$'\033[97m'; GR=$'\033[32m'; RD=$'\033[31m'
YL=$'\033[33m'; CY=$'\033[36m'; GY=$'\033[90m'
OR=$'\033[38;5;208m'
[[ -t 1 && -z "${NO_COLOR:-}" ]] || { NC=''; B=''; D=''; WH=''; GR=''; RD=''; YL=''; CY=''; GY=''; OR=''; }

trap 'printf "\n  %bInterrupted.%b\n" "$RD" "$NC" >&2; exit 130' INT TERM

line()  { printf '  %b\n' "$*" >&2; }

step()  { line "${GR}✓${NC}  $*"; }

info()  { line "${OR}→${NC}  $*"; }

warn()  { line "${YL}!${NC}  $*"; }

fail()  { line "${RD}✗${NC}  $*"; }

kv()    { printf '  %b%-14s%b %b\n' "$GY" "$1" "$NC" "$2" >&2; }

hr()    { line "${GY}──────────────────────────────────────────────${NC}"; }

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
