#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Part of scripts/lib (the simulated installer repo): sourced by manager.sh,
# mirrored function-for-function inside install.sh (curl-pipe standalone).
# SYNC: tests/test_lib_parity.py enforces the mirror. Pure helpers only.
# Password policy + release artifact URLs.

admin_password_problem() {
    local pass="$1" lowered
    [[ -n "$pass" ]] || { printf 'must not be empty'; return 0; }
    [[ "$pass" != *$'\n'* && "$pass" != *$'\r'* ]] \
        || { printf 'must be a single line'; return 0; }
    [[ ${#pass} -ge 8 ]] \
        || { printf 'must be at least 8 characters (the panel requires >= 8)'; return 0; }
    lowered="${pass,,}"
    case "$lowered" in
        *change-me*|*changeme*|*change_me*|*password123*|*admin123*)
            printf 'looks like a placeholder — choose a strong password (the panel rejects change-me/changeme/change_me/password123/admin123)' ;;
    esac
    return 0
}

validate_admin_password() {
    local problem
    problem="$(admin_password_problem "$1")"
    [[ -z "$problem" ]] || die "Admin password $problem"
}

prompt_validate_admin_password() {
    local tries=0 problem
    while (( tries < 3 )); do
        problem="$(admin_password_problem "$ADMIN_PASS")"
        if [[ -z "$problem" ]]; then
            step "Password set (hidden while typing)"
            return 0
        fi
        warn "Weak password: $problem"
        tries=$((tries + 1))
        [[ $tries -lt 3 ]] && ADMIN_PASS="$(ask "Admin password" "" "h")"
    done
    die "No acceptable password after 3 tries (need >= 8 characters, not a common word)"
}

release_base() { printf '%s-%s' "$APP_SLUG" "$VERSION"; }

release_url() {
    printf 'https://github.com/%s/releases/download/v%s/%s.tar.gz' \
        "$REPO" "$VERSION" "$(release_base)"
}

release_checksum_url() {
    printf 'https://github.com/%s/releases/download/v%s/%s.sha256' \
        "$REPO" "$VERSION" "$(release_base)"
}
