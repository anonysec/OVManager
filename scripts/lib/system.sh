#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Part of scripts/lib (the simulated installer repo): sourced by manager.sh,
# and fetched and sourced by install.sh at startup (curl-pipe standalone).
# One definition per helper — tests/test_lib_sourcing.py enforces that.
# Pure helpers only.
# Services, firewall, health, URLs.

# systemd waits up to TimeoutStopSec (90s default) for a stuck service, which
# operators read as a frozen installer. Bound the wait, then force the unit.
systemctl_bounded() {  # systemctl_bounded stop|restart|<other systemctl verb> [unit]
    local action="$1" unit="${2:-$SYSTEMD_SERVICE}" timeout="${OVM_STOP_TIMEOUT:-20}"
    case "$action" in
        stop)
            timeout "$timeout" systemctl stop "$unit" >/dev/null 2>&1 && return 0
            render_warn "Service stop timed out after ${timeout}s — force-killing $unit"
            systemctl kill -s KILL "$unit" >/dev/null 2>&1 || true
            return 0
            ;;
        restart)
            timeout "$timeout" systemctl restart "$unit" >/dev/null 2>&1 && return 0
            render_warn "Service restart timed out after ${timeout}s — force-restarting $unit"
            systemctl kill -s KILL "$unit" >/dev/null 2>&1 || true
            sleep 1
            systemctl start "$unit" >/dev/null 2>&1 || render_warn "Could not start $unit — check logs"
            return 0
            ;;
        *)
            # Anything else is a real systemctl verb, run as asked.
            #
            # This used to fall through to the restart branch, which meant
            # `systemctl_bounded daemon-reload` silently *restarted the
            # service* and never reloaded anything. The damage was not
            # theoretical: a 1.0.27 update failed verification, the failover
            # put the old unit back on disk, called this to reload it — and
            # systemd went on running the migrated unit, so the box was left
            # trying to start as a service account against a root-owned tree
            # and would not come up until someone ran daemon-reload by hand.
            timeout "$timeout" systemctl "$action" "$unit" >/dev/null 2>&1
            return $?
            ;;
    esac
}

# This box's public address, as Let's Encrypt would see it. Tried first from a
# public resolver (the address the internet routes to), then from the local
# interfaces, filtered to globally routable ranges.
public_ip() {
    local ip
    for ip in $(curl -fsS --max-time 3 https://api.ipify.org 2>/dev/null) \
              $(curl -fsS --max-time 3 https://ifconfig.me/ip 2>/dev/null); do
        [[ "$ip" =~ ^[0-9a-fA-F:.]+$ ]] && { printf '%s' "$ip"; return 0; }
    done
    for ip in $(hostname -I 2>/dev/null); do
        case "$ip" in
            *:*) continue ;;                       # skip IPv6: LE and the panel's TLS paths are v4 here
            127.*|10.*|192.168.*|169.254.*) continue ;;
            172.1[6-9].*|172.2[0-9].*|172.3[01].*) continue ;;   # 172.16/12 is private
            *) printf '%s' "$ip"; return 0 ;;
        esac
    done
    return 1
}

# Every routable address on this host, for a box with more than one. The
# Let's Encrypt prompt names them so an operator with several IPs can pick the
# one the certificate should carry instead of guessing.
public_ips() {
    local ip out=""
    for ip in $(hostname -I 2>/dev/null); do
        case "$ip" in
            *:*) continue ;;
            127.*|10.*|192.168.*|169.254.*) continue ;;
            172.1[6-9].*|172.2[0-9].*|172.3[01].*) continue ;;
            *) out+="$ip " ;;
        esac
    done
    printf '%s' "${out% }"
}

# Does this string look like a bare IP rather than a hostname? Decides whether
# a Let's Encrypt request is the short-lived IP kind or the ordinary domain one,
# so one free-text prompt can serve both.
is_ip_literal() {
    [[ "$1" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || [[ "$1" == *:* ]]
}

# Resolve and report, so a certificate attempt is not spent discovering a
# misconfigured record. Prints "<ip>" on success, empty otherwise.
resolve_host() {
    local host="$1"
    getent hosts "$host" 2>/dev/null | awk '{ print $1; exit }' || true
}

open_firewall_port() {
    local port="$1"
    if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
        ufw allow "$port/tcp" >/dev/null 2>&1 && render_ok "UFW allowed ${port}/tcp"
    elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null 2>&1 \
            && firewall-cmd --reload >/dev/null 2>&1 \
            && render_ok "firewalld allowed ${port}/tcp"
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

# wait_health_live — wait_health, but the running step's detail counts the
# attempts.
#
# The old wait was forty seconds of complete silence, which is indistinguishable
# from a hang and is the single most-reported "is this thing stuck?" moment in
# an install. Each poll updates the step line, so the operator sees it is
# trying and how long it has been trying.
wait_health_live() {  # wait_health_live <url> <tries>
    local url="$1" tries="${2:-30}" i ms=0 code=""
    for (( i = 1; i <= tries; i++ )); do
        code="$(curl -fskS -o /dev/null -w '%{http_code}' --max-time 3 "$url" 2>/dev/null || true)"
        if [[ "$code" == "200" ]]; then
            render_note "200 in ${ms}ms"
            return 0
        fi
        render_note "waiting · attempt ${i}/${tries}"
        sleep 1
        ms=$(( ms + 1000 ))
    done
    return 1
}

scheme_of() { [[ "${TLS_MODE:-none}" == "none" ]] && printf 'http' || printf 'https'; }

panel_url() {
    local host scheme
    host="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [[ -n "$host" ]] || host="127.0.0.1"
    scheme="$(scheme_of)"
    if [[ -n "${PATHPREFIX:-}" ]]; then
        printf '%s://%s:%s/%s/' "$scheme" "$host" "$PORT" "$PATHPREFIX"
    else
        printf '%s://%s:%s/' "$scheme" "$host" "$PORT"
    fi
}

port_in_use() {
    command -v ss >/dev/null 2>&1 || return 1
    # `found=1` + `exit !found`, not `exit 0`: awk still runs END after an
    # `exit 0` in a rule, so `END { exit 1 }` always won and this function
    # reported every port as free. Which meant the "port already in use"
    # guard never fired — not for a busy install port, and not for the port 80
    # check before Let's Encrypt.
    ss -ltn 2>/dev/null | awk -v p=":${1}$" '$4 ~ p { found = 1 } END { exit !found }'
}
