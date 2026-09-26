#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Part of scripts/lib (the simulated installer repo): sourced by manager.sh,
# mirrored function-for-function inside install.sh (curl-pipe standalone).
# SYNC: tests/test_lib_parity.py enforces the mirror. Pure helpers only.
# Services, firewall, health, URLs.

systemctl_bounded() {  # systemctl_bounded stop|restart [unit]
    local action="$1" unit="${2:-$SYSTEMD_SERVICE}" timeout="${OVM_STOP_TIMEOUT:-20}"
    if [[ "$action" == "stop" ]]; then
        timeout "$timeout" systemctl stop "$unit" >/dev/null 2>&1 && return 0
        warn "Service stop timed out after ${timeout}s — force-killing $unit"
        systemctl kill -s KILL "$unit" >/dev/null 2>&1 || true
        return 0
    fi
    timeout "$timeout" systemctl restart "$unit" >/dev/null 2>&1 && return 0
    warn "Service restart timed out after ${timeout}s — force-restarting $unit"
    systemctl kill -s KILL "$unit" >/dev/null 2>&1 || true
    sleep 1
    systemctl start "$unit" >/dev/null 2>&1 || warn "Could not start $unit — check logs"
    return 0
}

open_firewall_port() {
    local port="$1"
    if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
        ufw allow "$port/tcp" >/dev/null 2>&1 && step "UFW allowed ${port}/tcp"
    elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null 2>&1 \
            && firewall-cmd --reload >/dev/null 2>&1 \
            && step "firewalld allowed ${port}/tcp"
    fi
}

wait_health() {
    local url="$1" tries="${2:-30}" i
    for i in $(seq 1 "$tries"); do
        curl -fskS -o /dev/null --max-time 3 "$url" 2>/dev/null && return 0
        sleep 1
    done
    return 1
}

scheme_of() { [[ "${TLS_MODE:-none}" == "none" ]] && printf 'http' || printf 'https'; }

panel_url() {
    local host scheme
    host="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [[ -n "$host" ]] || host="127.0.0.1"
    scheme="$(scheme_of)"
    if [[ -n "$PATHPREFIX" ]]; then
        printf '%s://%s:%s/%s/' "$scheme" "$host" "$PORT" "$PATHPREFIX"
    else
        printf '%s://%s:%s/' "$scheme" "$host" "$PORT"
    fi
}

port_in_use() {
    command -v ss >/dev/null 2>&1 || return 1
    ss -ltn 2>/dev/null | awk -v p=":${1}$" '$4 ~ p {exit 0} END {exit 1}'
}
