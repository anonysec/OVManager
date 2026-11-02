#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# ovmanager operator CLI (hybrid: interactive TUI menu on bare TTY; direct subcommand on arguments)
set -eo pipefail

APP_DIR="${OVM_APP_DIR:-/opt/ovmanager}"
DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
SYSTEMD_SERVICE="ovmanager.service"

# Resolve server binary
SERVER_BIN="$APP_DIR/ovmanager-server"
if [[ ! -x "$SERVER_BIN" && -x "$APP_DIR/ovmanager" ]]; then
    SERVER_BIN="$APP_DIR/ovmanager"
fi

NC=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'; GR=$'\033[32m'; YL=$'\033[33m'; CY=$'\033[36m'; RD=$'\033[31m'; GY=$'\033[90m'
[[ -t 1 ]] || { NC=''; B=''; D=''; GR=''; YL=''; CY=''; RD=''; GY=''; }

show_help() {
    cat <<EOF
OVManager Operator CLI

Usage:
  ovmanager [command] [flags]
  ovmanager               (Open interactive menu when run on a terminal)

Commands:
  status                  Show panel status and health
  start                   Start the ovmanager systemd service
  stop                    Stop the ovmanager systemd service
  restart                 Restart the ovmanager systemd service
  logs [-f]               View panel service logs (journalctl)
  backup                  Create a database backup
  restore [file]          Restore database from backup
  tls                     Manage TLS/SSL certificates
  reset-password          Reset panel admin password
  update                  Update OVManager to the latest release
  uninstall [--purge]     Uninstall OVManager
  help                    Show this help

EOF
}

do_status() {
    printf '%b%s%b\n' "$CY" "OVManager Status" "$NC"
    if command -v systemctl >/dev/null 2>&1; then
        local state; state="$(systemctl is-active "$SYSTEMD_SERVICE" 2>/dev/null || true)"
        if [[ "$state" == "active" ]]; then
            printf '  Service: %b%s%b\n' "$GR" "active (running)" "$NC"
        else
            printf '  Service: %b%s%b\n' "$RD" "${state:-inactive}" "$NC"
        fi
    fi
    if [[ -x "$SERVER_BIN" ]]; then
        "$SERVER_BIN" status 2>/dev/null || true
    fi
}

do_logs() {
    local args=("$@")
    if [[ ${#args[@]} -eq 0 ]]; then
        journalctl -u "$SYSTEMD_SERVICE" -n 50 --no-pager
    else
        journalctl -u "$SYSTEMD_SERVICE" "${args[@]}"
    fi
}

do_update() {
    if [[ -f "$APP_DIR/install.sh" ]]; then
        bash "$APP_DIR/install.sh" update "$@"
    elif [[ -x "$SERVER_BIN" ]]; then
        "$SERVER_BIN" update "$@"
    else
        printf '%bError:%b installer or binary not found at %s\n' "$RD" "$NC" "$APP_DIR" >&2
        exit 1
    fi
}

do_uninstall() {
    if [[ -f "$APP_DIR/install.sh" ]]; then
        bash "$APP_DIR/install.sh" uninstall "$@"
    else
        printf '%bError:%b installer not found at %s/install.sh\n' "$RD" "$NC" "$APP_DIR" >&2
        exit 1
    fi
}

# ── Interactive TUI Menu ──────────────────────────────────────────────
run_interactive_menu() {
    while true; do
        printf '\n%bOVManager Operator Menu%b\n' "$CY" "$NC"
        printf '  %b1%b) Status & Health\n' "$B" "$NC"
        printf '  %b2%b) Start service\n' "$B" "$NC"
        printf '  %b3%b) Stop service\n' "$B" "$NC"
        printf '  %b4%b) Restart service\n' "$B" "$NC"
        printf '  %b5%b) View logs\n' "$B" "$NC"
        printf '  %b6%b) Backup database\n' "$B" "$NC"
        printf '  %b7%b) Restore backup\n' "$B" "$NC"
        printf '  %b8%b) Reset admin password\n' "$B" "$NC"
        printf '  %b9%b) Update OVManager\n' "$B" "$NC"
        printf ' %b10%b) Uninstall OVManager\n' "$B" "$NC"
        printf '  %b0%b) Quit\n' "$B" "$NC"
        printf '\nChoice [0-10]: '

        local choice
        read -r choice || break
        case "$choice" in
            1) do_status ;;
            2) systemctl start "$SYSTEMD_SERVICE" && printf '%bService started%b\n' "$GR" "$NC" ;;
            3) systemctl stop "$SYSTEMD_SERVICE" && printf '%bService stopped%b\n' "$YL" "$NC" ;;
            4) systemctl restart "$SYSTEMD_SERVICE" && printf '%bService restarted%b\n' "$GR" "$NC" ;;
            5) do_logs -f ;;
            6) [[ -x "$SERVER_BIN" ]] && "$SERVER_BIN" backup || printf '%bServer binary missing%b\n' "$RD" "$NC" ;;
            7) [[ -x "$SERVER_BIN" ]] && "$SERVER_BIN" restore || printf '%bServer binary missing%b\n' "$RD" "$NC" ;;
            8) [[ -x "$SERVER_BIN" ]] && "$SERVER_BIN" reset-password || printf '%bServer binary missing%b\n' "$RD" "$NC" ;;
            9) do_update ;;
            10) do_uninstall; break ;;
            0|q|Q) break ;;
            *) printf '%bInvalid choice%b\n' "$RD" "$NC" ;;
        esac
    done
}

# ── Argument Dispatching ───────────────────────────────────────────────
main() {
    if [[ $# -gt 0 ]]; then
        local cmd="$1"
        shift
        case "$cmd" in
            status)         do_status "$@" ;;
            start|stop|restart|enable|disable)
                            systemctl "$cmd" "$SYSTEMD_SERVICE" ;;
            logs)           do_logs "$@" ;;
            update)         do_update "$@" ;;
            uninstall)      do_uninstall "$@" ;;
            backup|restore|tls|reset-password|health|auth)
                            [[ -x "$SERVER_BIN" ]] || { printf '%bError:%b %s missing\n' "$RD" "$NC" "$SERVER_BIN" >&2; exit 1; }
                            exec "$SERVER_BIN" "$cmd" "$@" ;;
            help|-h|--help) show_help ;;
            *)
                            if [[ -x "$SERVER_BIN" ]]; then
                                exec "$SERVER_BIN" "$cmd" "$@"
                            else
                                show_help
                                exit 1
                            fi
                            ;;
        esac
        exit 0
    fi

    # Bare invocation
    if [[ -t 0 && -t 1 ]]; then
        run_interactive_menu
    else
        show_help
    fi
}

main "$@"
