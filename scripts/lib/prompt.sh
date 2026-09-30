#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Part of scripts/lib (the simulated installer repo): sourced by manager.sh,
# and fetched and sourced by install.sh at startup (curl-pipe standalone).
# One definition per helper — tests/test_lib_sourcing.py enforces that.
# Pure helpers only.
# Interactive prompts, menus, spinners.

# Interactive only when -y was not passed and a terminal is reachable: `curl |
# bash` has no stdin TTY, though /dev/tty usually works.
can_prompt() {
    [[ "${YES:-0}" -eq 0 ]] || return 1
    [[ -t 0 ]] && return 0
    # /dev/tty can exist but be unopenable (containers, detached shells):
    # actually try to open it, or prompts silently fall back to defaults.
    { : </dev/tty; } 2>/dev/null && return 0
    return 1
}

# Interactive menu only: scripts and pipes take the subcommand path instead.
has_tty() {
    [[ -t 0 ]] && return 0
    { : </dev/tty; } 2>/dev/null && return 0
    return 1
}

# Reads stdin, so callers redirect /dev/tty when needed.
_masked_read() {
    local buf="" ch
    while IFS= read -rsn1 ch; do
        case "$ch" in
            ""|$'\n'|$'\r') break ;;
            $'\x7f'|$'\b')
                if [[ -n "$buf" ]]; then buf="${buf%?}"; printf '\b \b' >&2; fi ;;
            *) buf+="$ch"; printf '*' >&2 ;;
        esac
    done
    printf '\n' >&2
    printf '%s' "$buf"
}

_read_reply() {  # hidden? → prints the line on stdout
    local hidden="${1:-}" buf=""
    if [[ -t 0 ]]; then
        if [[ "$hidden" == "h" ]]; then _masked_read; return 0; fi
        read -r buf
    elif [[ -e /dev/tty && -r /dev/tty ]]; then
        if [[ "$hidden" == "h" ]]; then _masked_read </dev/tty; return 0; fi
        read -r buf </dev/tty
    else
        return 1
    fi
    printf '%s' "$buf"
}

ask() {  # ask <label> <default> [hidden]
    local label="$1" default="$2" hidden="${3:-}" val=""
    if can_prompt; then
        render_ask "$label" "$default"
        val="$(_read_reply "$hidden")" || true
    fi
    [[ -n "$val" ]] || val="$default"
    printf '%s' "$val"
}

# confirm <question> [default] — default is y, which is what an unattended run
# gets. A destructive caller must pass n: answering "yes" on nobody's behalf
# made `ovm rollback` replace the running install from a cron job or pipeline.
confirm() {
    [[ "${YES:-0}" -eq 1 ]] && return 0
    local default="${2:-y}"
    if ! can_prompt; then
        [[ "$default" == "y" ]]
        return
    fi
    render_ask "$1" "$([ "$default" = y ] && printf 'Y/n' || printf 'y/N')"
    local c=""
    c="$(_read_reply)" || true
    [[ ! "$c" =~ ^[Nn]$ ]]
}

# Explicit-yes prompt (default NO): non-interactive runs keep the safe answer.
confirm_no() {
    [[ "${YES:-0}" -eq 1 ]] && return 1
    can_prompt || return 1
    render_ask "$1" "y/N"
    local c=""
    c="$(_read_reply)" || true
    [[ "$c" =~ ^[Yy]$ ]]
}

# confirm_word <question> <word> — the destructive default. `uninstall` asks
# for the word "purge" before it deletes a database, and Enter keeps the data.
# A plain y/N made the destructive answer one stray keystroke away from the
# default, which is the wrong way round.
confirm_word() {
    local question="$1" word="$2" reply=""
    [[ "${YES:-0}" -eq 1 ]] && return 0
    can_prompt || return 1
    render_ask "$question" "press enter to keep it"
    reply="$(_read_reply)" || true
    [[ "$reply" == "$word" ]]
}

run_step() {
    local label="$1"; shift
    "$@" >/dev/null 2>&1 &
    local pid=$! rc=0
    render_watch
    wait "$pid" 2>/dev/null || rc=$?
    if [[ $rc -eq 0 ]]; then
        render_done ""
        return 0
    fi
    render_fail "$label" "command failed with status $rc"
    return 1
}

# Menu. The drawing and the keystrokes belong to render.sh; this is the
# ask-side wrapper for callers that just want a tag back.
#
# The old version preferred whiptail when it happened to be installed, which
# meant the same menu rendered two completely different ways on two different
# boxes. One renderer, so the pointer, the number and the arrow always agree.
tui_select() { render_menu "$@"; }
