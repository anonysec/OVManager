#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Part of scripts/lib (the simulated installer repo): sourced by manager.sh,
# and fetched and sourced by install.sh at startup (curl-pipe standalone).
# One definition per helper — tests/test_lib_sourcing.py enforces that.
# Pure helpers only.
# Password policy + release artifact URLs.

# Mirrors the panel's boot-time validation (backend/config.py): >= 8 chars
# and no placeholder-looking values.
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

# Interactive re-prompt until the typed password passes the panel's rules
# (max 3 tries, then fail fast — never install a password the panel rejects).
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

# ── Owner claim key ────────────────────────────────────────────────────
# The installer mints this instead of an owner password. The panel reads the
# file on every claim attempt, so a regenerated key works with no restart, and
# deletes it once the claim succeeds — which is why regenerating is safe: it is
# not the credential, it is the invitation.
claim_key_path() { printf '%s/owner-claim.key' "$DATA_DIR"; }

# mint_claim_key → writes the key 0600 and prints it (stdout only).
#
# Ownership follows the panel's: the data dir is the service account's on a
# native install and uid 1000's under Docker, and a key those users cannot read
# is a key that cannot be claimed.
mint_claim_key() {
    local path key owner=""
    path="$(claim_key_path)"
    key="$(rand_hex | cut -c1-32)"
    mkdir -p "$DATA_DIR"
    ( umask 077; printf '%s\n' "$key" > "$path" ) || die "Could not write $path"
    chmod 600 "$path" 2>/dev/null || true
    if [[ "${MODE:-}" == "docker" || ( -z "${MODE:-}" && -f "$DATA_DIR/ovmanager-compose.yml" ) ]]; then
        owner="1000:1000"
    elif [[ -n "${PANEL_USER:-}" ]]; then
        owner="$PANEL_USER:$PANEL_USER"
    fi
    [[ -n "$owner" ]] && chown "$owner" "$path" 2>/dev/null || true
    printf '%s\n' "$key"
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
