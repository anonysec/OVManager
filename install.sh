#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# OVManager installer, bootstraps the Go binary (PasarGuard-style).
#
set -Eeuo pipefail

REPO="${OVM_REPO:-anonysec/OVManager}"
APP_SLUG="ovmanager"
SERVER_BIN="ovmanager-server"
INSTALL_DIR="${OVM_INSTALL_DIR:-/opt/ovmanager}"
DATA_DIR="${OVM_DATA_DIR:-/var/lib/ovmanager}"
DEFAULT_PORT="${OVM_DEFAULT_PORT:-2095}"
DEFAULT_URLPATH="${OVM_DEFAULT_URLPATH:-dashboard}"
DEFAULT_USER="admin"
SYSTEMD_SERVICE="ovmanager.service"
VERSION="${OVM_VERSION:-latest}"
if [[ -f internal/version/version.go ]]; then
    VERSION=$(grep -E '^(const|var) Version = ' internal/version/version.go | sed -E 's/.*"([^"]+)".*/\1/')
fi
# Resolve "latest" to the newest published release tag.
is_legacy_prereset() {
    local v="${1#v}"
    if [[ "$v" =~ ^2\.[1-4]\. ]]; then
        return 0
    fi
    return 1
}

if [[ "$VERSION" == "latest" ]]; then
    if ! VERSION="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\([^"]*\)".*/\1/p' | head -n1)"; then
        VERSION=""
    fi
    [[ -n "$VERSION" ]] || { echo "Could not resolve latest release for $REPO" >&2; exit 1; }
fi

if is_legacy_prereset "$VERSION"; then
    echo "Refusing legacy pre-reset release v$VERSION (current line is >= 2.0.0)" >&2
    exit 1
fi
BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"
PANEL_USER="${OVM_PANEL_USER:-ovmanager}"
CLI_NAME="ovmanager"

PORT_VAL="${OVM_PORT:-$DEFAULT_PORT}"
URLPATH_VAL="${OVM_URLPATH:-$DEFAULT_URLPATH}"
DB_TYPE="${OVM_DB_TYPE:-sqlite}"
DB_URL="${OVM_DATABASE_URL:-}"
HEALTH_TIMEOUT="${OVM_HEALTH_TIMEOUT:-40}"
ACME_TIMEOUT="${OVM_ACME_TIMEOUT:-60}"
INTERACTIVE=0
YES=0
FROM_SOURCE=0
SRC=""
DEST=""
ACTION="install"
ACTION_GIVEN=0
UPDATE_ARGS=()

SSL_MODE="${OVM_SSL_MODE:-}"
SSL_DOMAIN="${OVM_ACME_DOMAIN:-}"
SSL_CERT_SRC=""
# shellcheck shell=bash
SSL_KEY_SRC=""
SSL_IP=""
INSTALL_IP_SSL=0
INSTALL_SELF_SIGNED=0
SELF_SIGNED_TARGET=""

# ── Capability detection (OVNode-compatible) ────────────────────────
if [[ -t 2 && -z "${NO_COLOR:-}" && "${TERM:-dumb}" != "dumb" ]]; then
    RENDER_COLOR=1
else
    RENDER_COLOR=0
fi
if [[ "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" == *[Uu][Tt][Ff]* ]]; then
    RENDER_SPINNER_UNICODE=1
else
    RENDER_SPINNER_UNICODE=0
fi
NC=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'
WH=$'\033[97m'; GR=$'\033[32m'; RD=$'\033[31m'
YL=$'\033[33m'; CY=$'\033[36m'; GY=$'\033[90m'
OR=$'\033[38;5;208m'
[[ "$RENDER_COLOR" -eq 1 ]] || { NC=''; B=''; D=''; WH=''; GR=''; RD=''; YL=''; CY=''; GY=''; OR=''; }
if [[ "$RENDER_SPINNER_UNICODE" -eq 1 ]]; then
    RENDER_OK='✓'; RENDER_BAD='✗'; RENDER_RULE='──────────────────────────────────────────────'
else
    RENDER_OK='ok'; RENDER_BAD='XX'; RENDER_RULE='----------------------------------------------'
fi
[[ -t 2 ]] || { NC=''; B=''; D=''; WH=''; GR=''; RD=''; YL=''; CY=''; GY=''; OR=''; }

_render_paint() { if [[ "$RENDER_COLOR" -eq 1 ]]; then printf '%b%s%b' "$1" "$2" "${NC:-}"; else printf '%s' "$2"; fi; }
_render_out() { printf '  %b\n' "$*" >&2; }

# Legacy aliases (kept for existing call sites)
_GREEN="$GR"; _YELLOW="$YL"; _BLUE="$CY"; _RED="$RD"; _CYAN="$CY"
_BOLD="$B"; _DIM="$D"; _RESET="$NC"
colorized_echo() {
    local color="$1"; shift
    case "$color" in
        green)  printf '%s%s%s\n' "$GR" "$*" "$NC" >&2 ;;
        yellow) printf '%s%s%s\n' "$YL" "$*" "$NC" >&2 ;;
        red)    printf '%s%s%s\n' "$RD" "$*" "$NC" >&2 ;;
        blue)   printf '%s%s%s\n' "$CY" "$*" "$NC" >&2 ;;
        cyan)   printf '%s%s%s\n' "$CY" "$*" "$NC" >&2 ;;
        *)      printf '%s\n' "$*" >&2 ;;
    esac
}
_ok()    { render_ok "$*"; }
_warn()  { render_warn "$*"; }
_err()   { render_fail "$*" "error"; }
_note()  { render_ask_note "$*"; }

section() { render_stage "$*"; }
step() { printf '%s[%s/%s]%s %s\n' "$D" "$1" "$2" "$NC" "$3" >&2; }

die()    { printf '\n  %sError:%s %s\n\n' "$RD" "$NC" "$*" >&2; exit 1; }

has_systemd() { command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; }
check_root()  { [[ "$EUID" -eq 0 ]] || die "Must run as root (sudo)."; }
install_packages() {
    local pkgs=("$@")
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq >/dev/null 2>&1 || true
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${pkgs[@]}" >/dev/null 2>&1 || return 1
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y -q "${pkgs[@]}" >/dev/null 2>&1 || return 1
    elif command -v yum >/dev/null 2>&1; then
        yum install -y -q "${pkgs[@]}" >/dev/null 2>&1 || return 1
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache "${pkgs[@]}" >/dev/null 2>&1 || return 1
    else
        return 1
    fi
    return 0
}

check_deps() {
    local missing_pkgs=()
    command -v curl >/dev/null 2>&1 || missing_pkgs+=("curl")
    command -v openssl >/dev/null 2>&1 || missing_pkgs+=("openssl")
    if [[ ${#missing_pkgs[@]} -gt 0 ]]; then
        _note "installing missing dependencies: ${missing_pkgs[*]}"
        install_packages "${missing_pkgs[@]}" || die "Could not install: ${missing_pkgs[*]}"
    fi
    for cmd in curl install openssl; do
        command -v "$cmd" >/dev/null 2>&1 || die "Missing required tool: $cmd"
    done
}

is_domain() { [[ "$1" =~ ^([A-Za-z0-9](-*[A-Za-z0-9])*\.)+(xn--[a-z0-9]{2,}|[A-Za-z]{2,})$ ]]; }
is_ipv4() {
    local ip="$1" IFS='.' octets=()
    [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
    read -r -a octets <<<"$ip"
    [[ ${#octets[@]} -eq 4 ]] || return 1
    for octet in "${octets[@]}"; do (( octet >= 0 && octet <= 255 )) || return 1; done
    return 0
}
is_ipv6() { [[ "$1" =~ : ]]; }
is_port_in_use() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk -v p=":${port}$" '$4 ~ p {found=1; exit} END {exit found ? 0 : 1}'
        return
    fi
    if command -v netstat >/dev/null 2>&1; then
        netstat -lnt 2>/dev/null | awk -v p=":${port} " '$4 ~ p {found=1; exit} END {exit found ? 0 : 1}'
        return
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1 && return 0
    fi
    return 1
}
get_public_ipv4() {
    local urls=("https://api4.ipify.org" "https://ipv4.icanhazip.com" "https://v4.ident.me")
    local server_ip url
    for url in "${urls[@]}"; do
        server_ip=$(curl -4 -fsS --max-time 5 "$url" 2>/dev/null | tr -d '[:space:]' || true)
        if is_ipv4 "$server_ip"; then printf '%s' "$server_ip"; return 0; fi
    done
    return 1
}

# All globally routable IPv4 addresses on this host (PasarGuard-style hint).
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

detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64) printf 'amd64' ;;
        aarch64|arm64) printf 'arm64' ;;
        *) die "Unsupported architecture: $(uname -m)" ;;
    esac
}
release_asset() { printf '%s-linux-%s' "$APP_SLUG" "$(detect_arch)"; }
release_tag() { case "$VERSION" in dev|dev-*) printf 'dev' ;; *) printf 'v%s' "$VERSION" ;; esac; }
release_url() { printf 'https://github.com/%s/releases/download/%s/%s' "$REPO" "$(release_tag)" "$(release_asset)"; }
release_sums_url() { printf 'https://github.com/%s/releases/download/%s/SHA256SUMS' "$REPO" "$(release_tag)"; }


fetch_release() {
    local dest="$1" work asset retries=0
    asset="$(release_asset)"
    work="$(mktemp -d)"
    _note "fetching v$VERSION ($asset)"
    while true; do
        if curl -fsSL --max-time 300 --retry 3 --retry-delay 2 --retry-max-time 600 -o "$work/$asset" "$(release_url)" 2>/dev/null; then
            break
        fi
        retries=$((retries + 1))
        if [[ $retries -ge 3 ]]; then rm -rf "$work"; die "No release file for v$VERSION"; fi
        sleep $((2 ** retries))
    done
    curl -fsSL --max-time 60 --retry 3 --retry-delay 2 --retry-max-time 120 -o "$work/SHA256SUMS" "$(release_sums_url)" 2>/dev/null || { rm -rf "$work"; die "Could not download SHA256SUMS for v$VERSION, refusing to install an unverified release"; }
    ( cd "$work" && grep " $asset\$" SHA256SUMS | sha256sum -c - >/dev/null ) || { rm -rf "$work"; die "Checksum verification failed for $asset (v$VERSION): SHA256SUMS is missing a line for $asset or the download does not match, refusing to install"; }
    mkdir -p "$dest"
    install -m 0755 "$work/$asset" "$dest/$SERVER_BIN"
    chown root:root "$dest/$SERVER_BIN"
    ln -sf "$SERVER_BIN" "$dest/$APP_SLUG"
    rm -rf "$work"
    _ok "installed v$VERSION to $dest"
}

validate_port() { local p="$1"; [[ "$p" =~ ^[0-9]+$ ]] && [[ "$p" -ge 1 && "$p" -le 65535 ]]; }
validate_urlpath() {
    local p="$1"
    [[ "$p" != "api" && "$p" != "assets" && "$p" != "health" && "$p" != "static" && "$p" != "doc" && "$p" != "openapi.json" ]] || return 1
    [[ "$p" =~ ^[A-Za-z0-9_-]+$ ]]
}

# ── Interactive menu ────────────────────────────────────────────────────
# The install wizard is a sequence of small numbered menus over a shared
# frame: a blue rule, aligned numbered rows, and one prompt line at the end.
# Everything prints to stderr so `curl | bash` stays clean.

# ── OVNode render helpers (verbatim port) ────────────────────────────
RENDER_LABEL_W=14
_render_paint() { if [[ "$RENDER_COLOR" -eq 1 ]]; then printf '%b%s%b' "$1" "$2" "${NC:-}"; else printf '%s' "$2"; fi; }
_render_out() { printf '  %b\n' "$*" >&2; }

render_banner() {  # render_banner <name> <version>
    local name="$1" version="$2"
    _render_out "$(_render_paint "$B" "$name")  $version  $(_render_paint "$GY" "· anonysec")"
    render_rule
}

render_rule() { _render_out "$(_render_paint "$GY" "$RENDER_RULE")"; }

render_screen() {
    [[ -t 2 ]] || return 0
    clear 2>/dev/null || printf '\033[H\033[2J\033[3J' >&2 || true
    return 0
}

render_menu() {
    shift    # title is the caller's; the banner already said what this is
    local -a tags=() labels=()
    while [[ $# -ge 2 ]]; do tags+=("$1"); labels+=("$2"); shift 2; done
    local count=${#tags[@]}
    [[ "$count" -gt 0 ]] || return 1
    local i=0
    while (( i < count )); do
        printf '  %b%d%b  %s\n' "$B" "$(( i + 1 ))" "$NC" "${labels[$i]}" >&2
        i=$(( i + 1 ))
    done
    local n
    n="$(ask "choice" "1")"
    [[ "$n" =~ ^[0-9]+$ ]] || n=1
    printf '%s' "${tags[$(( ((10#$n - 1) + count) % count ))]}"
    return 0
}

RENDER_STEP_LABEL=""
render_begin() { RENDER_STEP_LABEL="$1"; printf '  %b..%b    %s\n' "$GY" "$NC" "$1" >&2; return 0; }
render_stage() { printf '\n  ============================== %s ==============================\n' "$1" >&2; return 0; }
render_done() { RENDER_STEP_LABEL=""; printf '  %b%s%b  %s\n' "$GR" "$RENDER_OK" "$NC" "${1:-}" >&2; return 0; }
render_end() { RENDER_STEP_LABEL=""; return 0; }
render_note() { printf '  %b..%b    %s\n' "$GY" "$NC" "$1" >&2; return 0; }
render_line() { _render_out "$*"; }
render_blank() { printf '\n' >&2; }
render_ok() { printf '  %b%s%b  %s\n' "$GR" "$RENDER_OK" "$NC" "$1" >&2; }
render_warn() { printf '  %b%s%b\n' "$YL" "$1" "$NC" >&2; }
render_kv() { printf '   %b%-*s%b %s\n' "$GY" "$RENDER_LABEL_W" "$1" "$NC" "$2" >&2; }
render_kv_w() { printf '   %b%-*s%b %s\n' "$GY" "$1" "$2" "$NC" "$3" >&2; }
render_key() { printf '   %b%-*s%b %b%s%b\n' "$GY" "$RENDER_LABEL_W" "$1" "$NC" "$B" "$2" "$NC" >&2; }
render_url() { render_kv "$1" "$(_render_paint "$B" "$2")"; }
render_fail() { RENDER_STEP_LABEL=""; printf '  %b%s%b %b%s%b  %s\n' "$RD" "$RENDER_BAD" "$NC" "$B" "$1" "$NC" "$2" >&2; return 0; }
render_next() { printf '  %bnext%b  %s · uninstall: %s\n' "$GY" "$NC" "$1" "$2" >&2; }
render_ask() { printf '  %b%s%b %b[%s]%b: ' "$GY" "$1" "$NC" "$B" "$2" "$NC" >&2; }
render_ask_note() { _render_out "$(_render_paint "$GY" "$1")"; }

# is_tty, OVNode-compatible: terminal on both ends.
is_tty() { [[ -t 0 && -t 2 ]]; }
ask() {
    local label="$1" default="$2" hidden="${3:-}" val=""
    if is_tty && [[ "${YES:-0}" -eq 0 ]]; then
        render_ask "$label" "$default"
        if [[ "$hidden" == "h" ]]; then
            local buf="" ch
            while IFS= read -rsn1 ch; do
                case "$ch" in
                    ""|$'\n'|$'\r') break ;;
                    $'\x7f'|$'\b') if [[ -n "$buf" ]]; then buf="${buf%?}"; printf '\b \b' >&2; fi ;;
                    *) buf+="$ch"; printf '*' >&2 ;;
                esac
            done
            printf '\n' >&2
            val="$buf"
        else
            read -r val
        fi
    fi
    echo "${val:-$default}"
}

# Legacy aliases kept for existing call sites.
ui_rule() { render_rule; }
ui_banner() { render_banner "$1" "$2"; }
ui_menu() { render_menu "" "$@"; }
_ok() { render_ok "$*"; }
_warn() { render_warn "$*"; }
_err() { render_fail "$*" "error"; }
_note() { render_ask_note "$*"; }
section() { render_stage "$*"; }
step() { printf '%s[%s/%s]%s %s\n' "$D" "$1" "$2" "$NC" "$3" >&2; }



prompt_interactive() {
    [[ "$INTERACTIVE" -eq 1 && "$YES" -eq 0 ]] || return 0
    [[ -t 0 ]] || return 0
    render_note "Press Enter to keep the bracketed default."
    local in_port in_path
    in_port="$(ask "panel port" "$PORT_VAL")"
    if [[ -n "${in_port// /}" ]]; then
        in_port="${in_port// /}"
        if validate_port "$in_port"; then PORT_VAL="$in_port"; else render_warn "Invalid port '$in_port', using default $PORT_VAL"; fi
    fi
    in_path="$(ask "panel url path" "$URLPATH_VAL")"
    in_path="${in_path// /}"; in_path="${in_path#/}"; in_path="${in_path%/}"
    if [[ -n "$in_path" ]]; then
        if validate_urlpath "$in_path"; then URLPATH_VAL="$in_path"; else render_warn "Invalid URL path '$in_path', using default $URLPATH_VAL"; fi
    fi
    local db_choice
    db_choice="$(ask "database type (sqlite/postgres/mysql)" "$DB_TYPE")"
    case "${db_choice:-sqlite}" in
        sqlite|postgres|mysql|mariadb) DB_TYPE="$db_choice" ;;
        *) render_warn "Unknown database '$db_choice', using sqlite" ; DB_TYPE="sqlite" ;;
    esac
    if [[ "$DB_TYPE" != "sqlite" && -z "$DB_URL" ]]; then
        DB_URL="$(ask "database URL (e.g. postgresql://user:pass@host:5432/ovmanager)" "")"
    fi
}

setup_ssl_wizard() {
    [[ "$INTERACTIVE" -eq 1 && "$YES" -eq 0 ]] || { [[ -n "$SSL_DOMAIN" ]] && SSL_MODE="domain"; return 0; }
    [[ -t 0 ]] || return 0
    render_stage "SSL setup"
    colorized_echo cyan "Choose SSL setup method for panel installation:"
    colorized_echo green "  1) Let's Encrypt Domain certificate"
    colorized_echo green "  2) Let's Encrypt IP certificate (short-lived)"
    colorized_echo green "  3) Custom certificate + key paths"
    colorized_echo yellow "  4) Self-signed certificate (testing)"
    colorized_echo yellow "  5) No SSL"
    colorized_echo yellow "Port 80 (or configured --ssl-http-port) must be reachable for Let's Encrypt."
    local choice
    read -p "Select SSL option [1-5] (default: 1): " choice
    choice="${choice// /}"
    [ -z "$choice" ] && choice="1"
    case "$choice" in
    1)
        SSL_MODE="domain"
        local recommended_ips
        recommended_ips="$(public_ips)"
        [[ -n "$recommended_ips" ]] && _note "this box answers on ${recommended_ips// /, }"
        while [[ -z "$SSL_DOMAIN" ]]; do
            SSL_DOMAIN="$(ask "domain for SSL certificate" "")"
            SSL_DOMAIN="${SSL_DOMAIN// /}"
            [[ -z "$SSL_DOMAIN" ]] && { render_fail "domain" "cannot be empty"; continue; }
            is_domain "$SSL_DOMAIN" || { render_fail "domain" "invalid format: $SSL_DOMAIN"; SSL_DOMAIN=""; }
        done
        ;;
    2)
        SSL_MODE="ip"
        local detected_ip input_ip recommended_ips
        detected_ip="$(get_public_ipv4 || true)"
        recommended_ips="$(public_ips)"
        [[ -n "$recommended_ips" ]] && _note "this box answers on ${recommended_ips// /, }"
        if [[ -n "$detected_ip" ]]; then
            input_ip="$(ask "IPv4 for SSL certificate" "$detected_ip")"
        else
            input_ip="$(ask "IPv4 for SSL certificate" "")"
        fi
        input_ip="${input_ip// /}"
        if [[ -z "$input_ip" && -n "$detected_ip" ]]; then input_ip="$detected_ip"; fi
        if ! is_ipv4 "$input_ip"; then render_fail "IPv4" "invalid: $input_ip"; SSL_MODE="none"; return 0; fi
        SSL_IP="$input_ip"; INSTALL_IP_SSL=1
        ;;
    3)
        SSL_MODE="custom"
        while true; do
            SSL_CERT_SRC="$(ask "full path to certificate file" "")"
            SSL_CERT_SRC=$(echo "$SSL_CERT_SRC" | tr -d '"' | tr -d "'" | xargs)
            [[ -f "$SSL_CERT_SRC" && -r "$SSL_CERT_SRC" && -s "$SSL_CERT_SRC" ]] && break
            render_fail "certificate" "file not found/readable: $SSL_CERT_SRC"
        done
        while true; do
            SSL_KEY_SRC="$(ask "full path to private key file" "")"
            SSL_KEY_SRC=$(echo "$SSL_KEY_SRC" | tr -d '"' | tr -d "'" | xargs)
            [[ -f "$SSL_KEY_SRC" && -r "$SSL_KEY_SRC" && -s "$SSL_KEY_SRC" ]] && break
            render_fail "private key" "file not found/readable: $SSL_KEY_SRC"
        done
        ;;
    4)
        SSL_MODE="selfsigned"
        local recommended_ips default_target ip
        recommended_ips=""
        # Suggest every address this box actually answers on, so the
        # self-signed certificate carries matching SAN entries (local,
        # public and loopback) instead of a single hostname.
        for ip in 127.0.0.1 $(hostname -I 2>/dev/null); do
            case "$ip" in *:*) continue ;; esac
            case " $recommended_ips " in *" $ip "*) continue ;; esac
            recommended_ips+="$ip "
        done
        for ip in $(public_ips); do
            case " $recommended_ips " in *" $ip "*) continue ;; esac
            recommended_ips+="$ip "
        done
        recommended_ips="${recommended_ips% }"
        [[ -n "$recommended_ips" ]] && _note "recommended (local/public/loopback): ${recommended_ips// /, }"
        default_target="${recommended_ips// /,}"
        [[ -z "$default_target" ]] && default_target="localhost"
        SELF_SIGNED_TARGET="$(ask "domain or IP(s) for self-signed cert" "$default_target")"
        SELF_SIGNED_TARGET="${SELF_SIGNED_TARGET// /}"
        [[ -z "$SELF_SIGNED_TARGET" ]] && SELF_SIGNED_TARGET="$default_target"
        INSTALL_SELF_SIGNED=1
        ;;
    5|*) SSL_MODE="none" ;;
    esac
}

check_acme_domain() {
    [[ -z "$SSL_DOMAIN" ]] && return 0
    if [[ -s "$DATA_DIR/tls/fullchain.pem" && -s "$DATA_DIR/tls/privkey.pem" ]]; then
        local check
        if check="$(openssl x509 -in "$DATA_DIR/tls/fullchain.pem" -noout -checkend 86400 2>/dev/null)" && [[ "$check" == "Certificate will not expire"* ]]; then
            _ok "acme    existing certificate still valid - skipping"
            SSL_DOMAIN=""; SSL_MODE="none"; return 0
        fi
    fi
    if (exec 3<>/dev/tcp/127.0.0.1/80) 2>/dev/null; then
        _warn "port 80 is in use - skipping auto ACME issuance"
        _note "free port 80, then run: ovmanager tls issue $SSL_DOMAIN"
        SSL_DOMAIN=""; SSL_MODE="none"; return 0
    fi
    if is_domain "$SSL_DOMAIN"; then
        _ok "acme    Let's Encrypt issuance scheduled for $SSL_DOMAIN"
    else
        _warn "OVM_ACME_DOMAIN '$SSL_DOMAIN' is not a valid DNS name"
        SSL_DOMAIN=""; SSL_MODE="none"
    fi
}

write_env() {
    local envfile="$1" data_dir="$2"
    if [[ -f "$envfile" ]]; then chmod 600 "$envfile" 2>/dev/null || true; return 0; fi
    mkdir -p "$data_dir"
    (
    umask 077
    {
        printf 'HOST=127.0.0.1\n'
        printf 'PORT=%s\n' "$PORT_VAL"
        printf 'URLPATH=%s\n' "$URLPATH_VAL"
        printf 'ADMIN_USERNAME=%s\n' "$DEFAULT_USER"
        printf 'DATA_DIR=%s\n' "$data_dir"
        if [[ "$DB_TYPE" != "sqlite" && -n "$DB_URL" ]]; then
            printf 'DATABASE_URL=%s\n' "$DB_URL"
        fi
        if [[ "$SSL_MODE" == "domain" && -n "$SSL_DOMAIN" ]]; then
            printf 'SSL_CERTFILE=%s/tls/fullchain.pem\n' "$data_dir"
            printf 'SSL_KEYFILE=%s/tls/privkey.pem\n' "$data_dir"
            printf 'OVM_ACME_DOMAIN=%s\n' "$SSL_DOMAIN"
            mkdir -p "$data_dir/tls"
        fi
        if [[ "$SSL_MODE" == "custom" ]]; then
            printf 'SSL_CERTFILE=%s\n' "$SSL_CERT_SRC"
            printf 'SSL_KEYFILE=%s\n' "$SSL_KEY_SRC"
        fi
        if [[ "$SSL_MODE" == "ip" || "$SSL_MODE" == "selfsigned" ]]; then
            printf 'SSL_CERTFILE=%s/tls/fullchain.pem\n' "$data_dir"
            printf 'SSL_KEYFILE=%s/tls/privkey.pem\n' "$data_dir"
        fi
    } > "$envfile"
    )
    cat >> "$envfile" <<'OPTS'

# ── Optional (uncomment to use) ────────────────────────────────────────
# PUBLIC_URL=https://panel.example.com
# SSL_CERTFILE=/path/to/fullchain.pem
# SSL_KEYFILE=/path/to/privkey.pem
# TRUSTED_PROXY=false
# OVM_ACME_DOMAIN=
# OVM_ACME_DIRECTORY_URL=
# OVM_ACME_HTTP_PORT=80
# OVM_TRAFFIC_POLL_SECONDS=10
# NODE_TLS_INSECURE_FALLBACK=false
OPTS
    chmod 600 "$envfile"
    chown "root:$PANEL_USER" "$envfile"
    chmod 640 "$envfile"
    _note "$envfile"
}

mint_claim_key() {
    local path="$1" key
    mkdir -p "$(dirname "$path")"
    [[ -f "$path" ]] && return 0
    key="$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-32)"
    ( umask 077; printf '%s\n' "$key" > "$path" )
    chmod 600 "$path"
    chown "$PANEL_USER:$PANEL_USER" "$path"
    printf '%s\n' "$key"
}

ensure_panel_user() {
    mkdir -p "$DATA_DIR"
    if ! id -u "$PANEL_USER" >/dev/null 2>&1; then
        useradd --system --no-create-home --home-dir "$DATA_DIR" --shell /usr/sbin/nologin --comment "OVManager panel service account" "$PANEL_USER" >/dev/null 2>&1 || die "Could not create the $PANEL_USER account"
    fi
    if getent group systemd-journal >/dev/null 2>&1; then
        usermod -a -G systemd-journal "$PANEL_USER" 2>/dev/null || true
    fi
}

unit_hardening() {
    local p
    for p in "$@"; do
        case "$p/" in /tmp/*|/var/tmp/*|/run/*|/home/*|/root/*|/dev/shm/*) return 0 ;; esac
    done
    printf 'NoNewPrivileges=yes\nPrivateTmp=yes\nProtectHome=yes\n'
}

write_systemd_unit() {
    local dest="${1:-$INSTALL_DIR}"
    cat > "/etc/systemd/system/$SYSTEMD_SERVICE" <<UNIT
[Unit]
Description=OVManager OpenVPN Panel
After=network.target

[Service]
Type=simple
WorkingDirectory=$dest
EnvironmentFile=$dest/.env
Environment="OVM_APP_DIR=$dest"
User=$PANEL_USER
Group=$PANEL_USER
SupplementaryGroups=systemd-journal
ExecStart=$dest/$SERVER_BIN
Restart=on-failure
RestartSec=3
AmbientCapabilities=CAP_NET_BIND_SERVICE
$(unit_hardening "$dest" "$DATA_DIR")

[Install]
WantedBy=multi-user.target
UNIT
    chmod 644 "/etc/systemd/system/$SYSTEMD_SERVICE"
}
grant_panel_access() {
    local dest="${1:-$INSTALL_DIR}"
    chmod 755 "$dest"; chmod 755 "$dest/$SERVER_BIN" 2>/dev/null || true
    mkdir -p "$DATA_DIR"; chown -R "$PANEL_USER:$PANEL_USER" "$DATA_DIR"; chmod 700 "$DATA_DIR"
    chown "root:$PANEL_USER" "$dest/.env"; chmod 640 "$dest/.env"
}
install_cli() {
    local dest="${1:-$INSTALL_DIR}"
    local src_cli
    src_cli="$(dirname "${BASH_SOURCE[0]}")/ovmanager.sh"
    if [[ -f "$src_cli" ]]; then
        install -m 0755 "$src_cli" "$dest/ovmanager.sh"
    fi
    mkdir -p "$BIN_DIR" 2>/dev/null || { _warn "Could not create $BIN_DIR"; return 0; }
    if [[ -f "$dest/ovmanager.sh" ]]; then
        ln -sf "$dest/ovmanager.sh" "$BIN_DIR/$CLI_NAME"
    else
        local target="$dest/$SERVER_BIN"
        [[ -x "$target" ]] || target="$dest/$APP_SLUG"
        ln -sf "$target" "$BIN_DIR/$CLI_NAME"
    fi
    _ok "command  $BIN_DIR/$CLI_NAME"
}

install_completion() {
    local dest="${1:-$INSTALL_DIR}"
    local completion_dir="/etc/bash_completion.d"
    local completion_file="$completion_dir/$CLI_NAME"
    mkdir -p "$completion_dir" 2>/dev/null || return 0
    if "$dest/$APP_SLUG" completion bash >"$completion_file" 2>/dev/null; then
        chmod 644 "$completion_file" 2>/dev/null || true
        _ok "completion  $completion_file"
    else
        rm -f "$completion_file" 2>/dev/null || true
    fi
}

uninstall_completion() {
    local completion_file="/etc/bash_completion.d/$CLI_NAME"
    if [[ -f "$completion_file" ]]; then
        rm -f "$completion_file" && _ok "removed $completion_file" || true
    fi
}

# Pin the OVNode installer to a fixed commit SHA.
OVNODE_COMMIT="41a8a2c0e9ddeb10d6c2dfddd947eab9e22d4015"

# OVNode's installer currently bootstraps its helpers into APP_DIR before it
# checks whether APP_DIR exists. Preserve the pre-bootstrap state when this
# exact upstream ordering is present; do not remove or overwrite existing nodes.
run_node_installer() {
    local script before='    load_helpers' check='    # install
    if [[ -d "$APP_DIR" ]]; then'
    local snapshot='    local ovm_node_dir_existed=0
    [[ -d "$APP_DIR" ]] && ovm_node_dir_existed=1
    load_helpers'
    local fixed_check='    # install
    if [[ "$ovm_node_dir_existed" -eq 1 ]]; then'

    local url="${OVN_INSTALLER_URL:-https://raw.githubusercontent.com/anonysec/OVNode/${OVNODE_COMMIT}/install.sh}"
    if ! script="$(curl -fsSL "$url")" || [[ -z "$script" ]]; then
        _warn "Could not download the OVNode installer."
        return 1
    fi
    local tmp
    tmp="$(mktemp)"
    printf '%s\n' "$script" > "$tmp"
    # Pin OVNode installer by commit SHA (OVNODE_COMMIT above); the downloaded
    # installer is executed as-is.
    if [[ "$script" == *"$before"*"$check"* && "$script" == *'load_helpers() {'* ]]; then
        script="${script/"$before"/"$snapshot"}"
        script="${script/"$check"/"$fixed_check"}"
        printf '%s\n' "$script" > "$tmp"
    fi
    chmod +x "$tmp"
    if [[ "$EUID" -eq 0 ]]; then
        OVN_YES=1 bash "$tmp"
    else
        sudo env OVN_YES=1 bash "$tmp"
    fi
    rm -f "$tmp"
}

# Print after the node installer (which clears the terminal), and before any
# unbounded log follow. Never read an old claim key merely to display it.
show_install_summary() {
    local port="$1" urlpath="$2" key="$3" display_path host_ip scheme=http public_ip=""
    display_path="${urlpath#/}"; display_path="${display_path%/}"
    [[ -n "$display_path" ]] && display_path="/${display_path}/" || display_path="/"
    if curl -fsSk --max-time 3 "https://127.0.0.1:${port}/health" >/dev/null 2>&1; then
        scheme=https
    fi
    # Prefer a publicly routable address for HTTPS (no tunnel needed); fall
    # back to the first local address when offline.
    if [[ -n "${OVM_HOST_IP:-}" ]]; then
        public_ip="$OVM_HOST_IP"
    elif [[ "$scheme" == "https" ]]; then
        public_ip="$(get_public_ipv4 || true)"
        if [[ -z "$public_ip" ]]; then
            for ip in $(hostname -I 2>/dev/null); do
                case "$ip" in
                    *:*) continue ;;
                    127.*|10.*|192.168.*|169.254.*) continue ;;
                    172.1[6-9].*|172.2[0-9].*|172.3[01].*) continue ;;
                    *) public_ip="$ip"; break ;;
                esac
            done
        fi
        public_ip="${public_ip:-<host>}"
    fi
    colorized_echo blue "Installation complete"
    if [[ "$scheme" == "https" ]]; then
        _ok "URL     ${scheme}://${public_ip}:$port$display_path"
    else
        _ok "URL     ${scheme}://127.0.0.1:$port$display_path"
    fi
    if [[ -n "$key" ]]; then
        _ok "Key     $key   (shown once, save it)"
    elif [[ -f "$DATA_DIR/owner-claim.key" ]]; then
        _note "existing claim key kept at $DATA_DIR/owner-claim.key"
    else
        _note "No new claim key was created (the panel may already be claimed)."
    fi
    if [[ "$scheme" != "https" ]]; then
        host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"; host_ip="${host_ip:-<host>}"
        _ok "SSH     ssh -L $port:127.0.0.1:$port $host_ip"
        _note "Open the URL through the SSH tunnel to access the panel."
    else
        _note "Open the URL in your browser (TLS is on)."
    fi
    [[ -n "$key" ]] && _note "Paste the key to claim the panel and set your password."
    return 0
}

offer_node_and_logs() {
    local mode port
    # mode kept for call-site compatibility (native/docker currently identical)
    mode="${1:-native}"
    port="$2" urlpath="$3" key="${4:-}" choice=""
    # PasarGuard-style: prompt even on a normal (non -i) install when a tty
    # is present; never block a piped/non-interactive run.
    if [[ "$YES" -eq 1 || ! -t 0 ]]; then
        _note "Skipping optional OVNode/logs prompts (non-interactive)."
        show_install_summary "$port" "$urlpath" "$key"
        return 0
    fi
    echo
    colorized_echo blue "=============================="
    colorized_echo yellow "OVManager doesn't have any OpenVPN core by default."
    colorized_echo yellow "You need at least one node for VPN connections."
    echo
    colorized_echo cyan "Want to install OVNode on the same server?"
    colorized_echo red "(Not recommended for commercial/production use)"
    echo
    read -r -p "Do you want to install OVNode on the same server? (y/n) " choice || true
    if [[ "$choice" =~ ^[Yy]$ ]]; then
        OVN_YES=1 run_node_installer || _warn "OVNode installation failed; the panel remains installed."
    else
        _note "Skipping OVNode installation."
    fi
    show_install_summary "$port" "$urlpath" "$key"
    echo
    choice=""
    read -r -p "Follow service logs? (y/n) " choice || true
    if [[ "$choice" =~ ^[Yy]$ ]]; then
        journalctl -u "$SYSTEMD_SERVICE" -f
    fi
}

verify_acme() {
    local data_dir="$1" cert key i check
    cert="$data_dir/tls/fullchain.pem"; key="$data_dir/tls/privkey.pem"
    _note "waiting for the Let's Encrypt certificate (up to $((ACME_TIMEOUT * 3))s)…"
    for ((i = 0; i < ACME_TIMEOUT; i++)); do
        if [[ -s "$cert" && -s "$key" ]]; then
            if check="$(openssl x509 -in "$cert" -noout -checkend 86400 2>/dev/null)" && [[ "$check" == "Certificate will not expire"* ]]; then
                _ok "acme    certificate installed at $cert"; return 0
            fi
        fi
        sleep 3
    done
    _warn "no Let's Encrypt certificate after 3 minutes, panel continues on plain HTTP"
    return 0
}

verify_health() {
    local port="$1" want="$2" i body got
    for ((i = 0; i < HEALTH_TIMEOUT; i++)); do
        body="$(curl -fsS --max-time 3 "http://127.0.0.1:${port}/health" 2>/dev/null || true)"
        if [[ -z "$body" ]]; then
            body="$(curl -fsSk --max-time 3 "https://127.0.0.1:${port}/health" 2>/dev/null || true)"
        fi
        if [[ -n "$body" ]]; then
            got="$(printf '%s' "$body" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)"
            # Dev builds report "dev-YYYYMMDD.N-sha"; accept any dev-* when want=dev.
            if [[ "$want" == "dev" && "$got" == dev-* ]] || [[ "$got" == "$want" ]]; then _ok "health  v$got on port $port"; return 0; fi
            [[ -n "$got" ]] && _warn "health reports '$got', expected '$want'"
        fi
        printf '.' >&2; sleep 1
    done
    printf '\n' >&2
    return 1
}

do_from_source() {
    local src="${SRC:-$PWD}" dest="${DEST:-$INSTALL_DIR}" service unit port key health
    [[ -d "$src" ]] || die "no source directory: $src"
    [[ -f "$src/cmd/main.go" ]] || die "no Go source tree in $src (cmd/main.go missing)"
    [[ -d "$src/web/dist" ]] || die "web/dist missing in $src, run: cd web && npm run build"
    check_root; ensure_panel_user
    [[ -n "$dest" && "$dest" != "/" ]] || die "refusing to operate on '$dest'"
    command -v rsync >/dev/null || die "rsync not found"
    command -v go >/dev/null || die "go not found, install Go 1.27+"
    dest="${dest%/}"
    if [[ "$dest" == "$INSTALL_DIR" ]]; then
        if [[ -e "$INSTALL_DIR/$APP_SLUG" || -e "/etc/systemd/system/$SYSTEMD_SERVICE" ]]; then
            die "--build refuses to overwrite the live install at $INSTALL_DIR; pass --dest DIR"
        fi
    fi
    service="$(basename "$dest").service"; unit="/etc/systemd/system/$service"
    rsync -a --delete --exclude .git --exclude .venv --exclude __pycache__ --exclude node_modules --exclude .pytest_cache --exclude .slim --exclude .env --exclude /data "$src/" "$dest/"
    mkdir -p "$dest/internal/webfs/dist"
    cp -a "$dest/web/dist/." "$dest/internal/webfs/dist/"
    ( cd "$dest" && go build -o "$SERVER_BIN" ./cmd )
    ln -sf "$SERVER_BIN" "$dest/$APP_SLUG"
    mkdir -p "$dest/data"; chown -R "$PANEL_USER:$PANEL_USER" "$dest/data"; chmod 700 "$dest/data"
    if [[ ! -f "$dest/.env" ]]; then
        cat > "$dest/.env" <<EOF
PORT=2095
URLPATH=dashboard
HOST=127.0.0.1
DATA_DIR=$dest/data
ADMIN_USERNAME=admin
EOF
        chown "root:$PANEL_USER" "$dest/.env"; chmod 640 "$dest/.env"
    fi
    if [[ ! -f "$dest/data/owner-claim.key" ]]; then
        key="$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-32)"
        ( umask 077; printf '%s\n' "$key" > "$dest/data/owner-claim.key" )
        chmod 600 "$dest/data/owner-claim.key"; chown "$PANEL_USER:$PANEL_USER" "$dest/data/owner-claim.key"
        _note "setup key (shown once): $key"
    fi
    port="$(awk -F= -v k=PORT '$1==k{print $2;exit}' "$dest/.env" 2>/dev/null)"; port="${port:-2095}"
    cat > "$unit" <<UNIT
[Unit]
Description=OVManager panel (dev install)
After=network.target

[Service]
Type=simple
WorkingDirectory=$dest
EnvironmentFile=$dest/.env
Environment="OVM_APP_DIR=$dest"
User=$PANEL_USER
Group=$PANEL_USER
SupplementaryGroups=systemd-journal
ExecStart=$dest/$SERVER_BIN
Restart=on-failure
RestartSec=3
$(unit_hardening "$dest" "$dest/data")
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
UNIT
    chmod 644 "$unit"
    systemctl daemon-reload
    systemctl restart "$service" 2>/dev/null || systemctl enable --now "$service" >/dev/null 2>&1 || true
    health=""
    for _ in $(seq 1 30); do
        curl -fsS --max-time 2 "http://127.0.0.1:$port/health" >/dev/null 2>&1 && { health=1; break; }
        sleep 1
    done
    [[ -n "$health" ]] || _warn "no /health on port $port yet, check: systemctl status $service"
    _ok "installed $dest (service $service, port $port)"
}

do_install() {
    render_banner "OVManager" "$VERSION"
    render_kv "repository" "${REPO}"
    render_kv "arch" "$(detect_arch)"
    render_kv "os" "$(. /etc/os-release 2>/dev/null && echo "$ID $VERSION_ID" || uname -s)"
    render_blank
    if [[ "$SSL_MODE" == "selfsigned" && "$INSTALL_SELF_SIGNED" -eq 0 ]]; then
        INSTALL_SELF_SIGNED=1
        [[ -z "$SELF_SIGNED_TARGET" ]] && SELF_SIGNED_TARGET="localhost"
    fi
    local dest="${DEST:-$INSTALL_DIR}"
    [[ -n "$dest" && "$dest" != "/" ]] || die "refusing to operate on '$dest'"
    check_root
    if [[ -e "$dest" ]]; then
        # Idempotent: a second run upgrades instead of failing. With -y (or no
        # tty) we upgrade in place without prompting; interactive runs still ask.
        local override="n"
        if [[ "${YES:-0}" -eq 1 ]] || ! is_tty; then
            override="y"
        else
            override="$(ask "OVManager already installed at $dest. Override previous installation?" "n")"
        fi
        if [[ "$override" =~ ^[Yy]$ ]]; then
            local purge="n"
            if [[ "${YES:-0}" -eq 0 ]] && is_tty; then
                purge="$(ask "Purge existing data at $DATA_DIR too?" "n")"
            fi
            if [[ "$purge" =~ ^[Yy]$ ]]; then
                rm -rf "$DATA_DIR"; _ok "purged $DATA_DIR"
            fi
            do_update "$@"
            return $?
        else
            render_warn "Aborted installation"; return 0
        fi
    fi
    has_systemd || die "systemd not found, a native install needs it"
    check_deps
    printf '# Executing ovmanager install script, commit: %s\n' "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --short HEAD 2>/dev/null || echo main)"
    colorized_echo blue "Configuration"
    prompt_interactive; setup_ssl_wizard
    [[ "$SSL_MODE" == "domain" && -n "$SSL_DOMAIN" ]] && check_acme_domain
    _ok "port=$PORT_VAL  path=$URLPATH_VAL  tls=${SSL_MODE:-none}"
    if is_port_in_use "$PORT_VAL"; then
        _warn "Port $PORT_VAL is already in use."
        if [[ "$INTERACTIVE" -eq 1 ]]; then
            local new_port
            while true; do
                new_port="$(ask "different port (1-65535) or q to abort" "")"
                new_port="${new_port// /}"
                [[ "$new_port" == "q" ]] && die "Installation aborted due to port conflict"
                if validate_port "$new_port"; then
                    if is_port_in_use "$new_port"; then _warn "Port $new_port is also in use."; else PORT_VAL="$new_port"; break; fi
                else
                    _warn "Invalid port: $new_port"
                fi
            done
        fi
    fi
    local key port urlpath
    colorized_echo blue "Creating panel user"; ensure_panel_user
    colorized_echo blue "Download"; fetch_release "$dest"
    colorized_echo blue "Writing environment file"; write_env "$dest/.env" "$DATA_DIR"
    key="$(mint_claim_key "$DATA_DIR/owner-claim.key")"
    colorized_echo blue "Installing systemd units"; write_systemd_unit "$dest"
    colorized_echo blue "Granting permissions"; grant_panel_access "$dest"
    colorized_echo blue "Installing CLI"; install_cli "$dest"; install_completion "$dest"
    colorized_echo blue "Service"
    systemctl daemon-reload
    if systemctl is-active --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then
        systemctl restart "$SYSTEMD_SERVICE" || die "Could not restart $SYSTEMD_SERVICE"
    else
        systemctl enable --now "$SYSTEMD_SERVICE" >/dev/null 2>&1 || die "Could not start $SYSTEMD_SERVICE"
    fi
    _ok "service $SYSTEMD_SERVICE started"
    if [[ "$INSTALL_SELF_SIGNED" -eq 1 ]]; then
        colorized_echo blue "TLS (self-signed)"
        if "$dest/$SERVER_BIN" tls selfsigned "${SELF_SIGNED_TARGET:-localhost}" >/dev/null 2>&1; then
            systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
            _ok "self-signed certificate issued for ${SELF_SIGNED_TARGET:-localhost}"
        else
            _warn "self-signed cert issuance failed"
        fi
    fi
    [[ "$SSL_MODE" == "custom" ]] && _ok "custom certificate configured (SSL_CERTFILE=$SSL_CERT_SRC)"
    if [[ "$SSL_MODE" == "domain" && -n "$SSL_DOMAIN" ]]; then
        colorized_echo blue "TLS (Let's Encrypt domain)"
        if "$dest/$SERVER_BIN" tls acme "$SSL_DOMAIN" >/dev/null 2>&1; then
            systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
            _ok "certificate issued for $SSL_DOMAIN"
        else
            _warn "domain certificate issuance failed - run 'ovmanager tls acme $SSL_DOMAIN' later"
        fi
    fi
    if [[ "$SSL_MODE" == "ip" && -n "$SSL_IP" ]]; then
        colorized_echo blue "TLS (Let's Encrypt IP)"
        if "$dest/$SERVER_BIN" tls acme "$SSL_IP" >/dev/null 2>&1; then
            systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
            _ok "IP certificate step done for $SSL_IP"
        else
            _warn "IP certificate issuance failed - run 'ovmanager tls acme $SSL_IP' later"
        fi
    fi
    port="$(awk -F= -v k=PORT '$1==k{print $2;exit}' "$dest/.env" 2>/dev/null)"; port="${port:-$DEFAULT_PORT}"
    urlpath="$(awk -F= -v k=URLPATH '$1==k{print $2;exit}' "$dest/.env" 2>/dev/null)"; urlpath="${urlpath:-$DEFAULT_URLPATH}"
    colorized_echo blue "Verification"
    verify_health "$port" "$VERSION" || die "The panel did not report v$VERSION on /health after 40s"
    _ok "installed v$VERSION to $dest (service $SYSTEMD_SERVICE, port $port)"
    [[ "$SSL_MODE" == "domain" && -n "$SSL_DOMAIN" ]] && verify_acme "$DATA_DIR"
    offer_node_and_logs native "$port" "$urlpath" "$key"
}

do_update() {
        local bin="$INSTALL_DIR/$SERVER_BIN"
    [[ -x "$bin" ]] || bin="$INSTALL_DIR/$APP_SLUG"
    [[ -x "$bin" ]] || die "not installed at $INSTALL_DIR, run the installer first"
    exec "$bin" update "$@"
}
do_status() {
    if [[ ! -d "$INSTALL_DIR" ]]; then render_fail "status" "Not Installed"; return 1; fi
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl is-active --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then render_ok "Status: Up"; else render_warn "Status: Down"; fi
    else render_ask_note "Status: Unknown (no systemd)"; fi
    [[ -x "$BIN_DIR/$CLI_NAME" ]] && "$BIN_DIR/$CLI_NAME" status 2>/dev/null || true
}
do_uninstall() {
    local purge=0 dest="${DEST:-$INSTALL_DIR}"
    [[ -n "$dest" && "$dest" != "/" ]] || die "refusing to operate on '$dest'"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --purge) purge=1; shift ;;
            -y|--yes) shift ;;
            *) die "Unknown option for uninstall: $1" ;;
        esac
    done
    # Check if installed (PasarGuard style)
    if [[ ! -d "$INSTALL_DIR" && ! -d "$DATA_DIR" ]]; then
        colorized_echo red "OVManager is not installed!"
        exit 1
    fi
    # Show what will be removed
    echo
    colorized_echo blue "=============================="
    colorized_echo yellow "The following will be removed:"
    [[ -d "$INSTALL_DIR" ]] && colorized_echo yellow "  - $INSTALL_DIR"
    [[ -d "$DATA_DIR" ]] && colorized_echo yellow "  - $DATA_DIR"
    colorized_echo blue "=============================="
    echo
    # Interactive confirmation (PasarGuard style)
    if [[ -t 0 && "$YES" -eq 0 && $# -eq 0 ]]; then
        local confirm purge_confirm
        confirm="$(ask "Do you really want to uninstall OVManager?" "n")"
        [[ "$confirm" =~ ^[Yy]$ ]] || { render_warn "Aborted."; return 0; }
        if [[ -d "$DATA_DIR" ]]; then
            purge_confirm="$(ask "remove data files too ($DATA_DIR)?" "n")"
            [[ "$purge_confirm" =~ ^[Yy]$ ]] && purge=1
        fi
    fi
    check_root
    if systemctl is-active --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then systemctl stop "$SYSTEMD_SERVICE"; _ok "stopped $SYSTEMD_SERVICE"; fi
    if systemctl is-enabled --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then systemctl disable "$SYSTEMD_SERVICE"; _ok "disabled $SYSTEMD_SERVICE"; fi
    for unit in $SYSTEMD_SERVICE; do
        [[ -f "/etc/systemd/system/$unit" ]] && { rm -f "/etc/systemd/system/$unit"; _ok "removed /etc/systemd/system/$unit"; }
    done
    systemctl daemon-reload 2>/dev/null || true
    for d in "$INSTALL_DIR" "$dest"; do [[ -d "$d" ]] && { rm -rf "$d"; _ok "removed $d"; }; done
    [[ -L "$BIN_DIR/$APP_SLUG" ]] && { rm -f "$BIN_DIR/$APP_SLUG"; _ok "removed $BIN_DIR/$APP_SLUG"; }
    uninstall_completion
    if [[ "$purge" -eq 1 ]]; then
        [[ -d "$DATA_DIR" ]] && { rm -rf "$DATA_DIR"; _ok "purged $DATA_DIR"; }
        id -u "$PANEL_USER" >/dev/null 2>&1 && { userdel "$PANEL_USER" 2>/dev/null && _ok "removed user $PANEL_USER" || true; }
    else
        _note "data preserved at $DATA_DIR (use --purge to remove)"
    fi
    colorized_echo green "OVManager uninstalled successfully"
}

usage() {
    cat <<EOF
OVManager Setup v${VERSION}

USAGE
  bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)

COMMANDS
  install                    Install OVManager (default)
  update [--version vX.Y.Z]  Hand off to \`ovmanager update\`
  uninstall [--purge]        Remove panel, service, and CLI
  status                     Show installation status
  up                         Start the panel
  down                       Stop the panel
  restart                    Restart the panel
  logs                       Tail panel logs
  cli                        Run the ovmanager CLI
  backup                     Run a backup now
  restore                    Restore a backup
  edit-env                   Edit the .env file
  install-script             (Re)install CLI + bash completion
  install-node               Install OVNode on this server
  version-script             Print installer version and commit
  help                       Show this help

OPTIONS
  -i, --interactive          Ask for port, URL path, and SSL setup
  -y, --yes                  Accept defaults without prompts
  --acme DOMAIN              Let's Encrypt certificate for DOMAIN
  --build [DIR]              Dev install from a working tree
  --dest DIR                 with --build: destination
  --version V                Override installer version (default from source tree)
  --ssl MODE                 SSL mode: domain|ip|custom|selfsigned|none
  --database TYPE            Database: sqlite|postgres|mysql (default sqlite)
  -h, --help                 Show this help

ENVIRONMENT
  OVM_PORT, OVM_URLPATH, OVM_ACME_DOMAIN, OVM_SSL_MODE, OVM_DB_TYPE, OVM_DATABASE_URL
  OVM_PANEL_USER, OVM_BIN_DIR, OVM_REPO
EOF
    exit 0
}
script_commit() {
    local dir candidate
    dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || { printf 'unknown'; return 0; }
    candidate="$dir"
    while [[ -n "$candidate" && "$candidate" != "/" ]]; do
        if [[ -e "$candidate/.git" ]]; then git -C "$candidate" rev-parse --short HEAD 2>/dev/null || printf 'unknown'; return 0; fi
        candidate="$(dirname -- "$candidate")"
    done
    printf 'unknown'
}
print_version_script() { local commit; commit="$(script_commit)"; printf 'installer  v%s\n' "$VERSION"; printf 'commit     %s\n' "$commit"; }

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --build|--from-source) FROM_SOURCE=1; shift; if [[ $# -ge 1 && "$1" != -* ]]; then SRC="$1"; shift; fi ;;
            --acme) [[ $# -ge 2 ]] || die "--acme needs a domain"; SSL_DOMAIN="$2"; SSL_MODE="domain"; shift 2 ;;
            --version) [[ $# -ge 2 ]] || die "--version needs a value"; VERSION="$2"; shift 2 ;;
            --ssl)  [[ $# -ge 2 ]] || die "--ssl needs a mode"; SSL_MODE="$2"; shift 2 ;;
            --database) [[ $# -ge 2 ]] || die "--database needs a type"; DB_TYPE="$2"; shift 2 ;;
            -i|--interactive) INTERACTIVE=1; shift ;;
            -y|--yes) YES=1; shift ;;
            -h|--help) usage ;;
            help) usage ;;
            status) ACTION="status"; ACTION_GIVEN=1; shift ;;
            version-script|script-version) ACTION="version-script"; ACTION_GIVEN=1; shift ;;
            update) ACTION="update"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            uninstall) ACTION="uninstall"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            up) ACTION="up"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            down) ACTION="down"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            restart) ACTION="restart"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            logs) ACTION="logs"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            cli) ACTION="cli"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            backup) ACTION="backup"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            restore) ACTION="restore"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            edit-env) ACTION="edit-env"; ACTION_GIVEN=1; shift ;;
            install-script) ACTION="install-script"; ACTION_GIVEN=1; shift ;;
            install-node) ACTION="install-node"; ACTION_GIVEN=1; shift ;;
            install) shift ;;
            interactive) INTERACTIVE=1; shift ;;
            *) die "Unknown option: $1  (see --help)" ;;
        esac
    done
}

up_command() {
    "$INSTALL_DIR/$SERVER_BIN" service start
}
down_command() {
    "$INSTALL_DIR/$SERVER_BIN" service stop
}
restart_command() {
    "$INSTALL_DIR/$SERVER_BIN" service restart
}
logs_command() {
    "$INSTALL_DIR/$SERVER_BIN" logs
}
cli_command() { local b="$INSTALL_DIR/$SERVER_BIN"; [[ -x "$b" ]] || b="$INSTALL_DIR/$APP_SLUG"; exec "$b" "$@"; }
backup_command() { local b="$INSTALL_DIR/$SERVER_BIN"; [[ -x "$b" ]] || b="$INSTALL_DIR/$APP_SLUG"; "$b" backup "$@"; }
restore_command() { local b="$INSTALL_DIR/$SERVER_BIN"; [[ -x "$b" ]] || b="$INSTALL_DIR/$APP_SLUG"; "$b" restore "$@"; }
edit_env_command() {
    local editor="${EDITOR:-nano}"
    command -v "$editor" >/dev/null 2>&1 || editor="vi"
    "$editor" "$INSTALL_DIR/.env"
}
install_script_command() { install_cli "$INSTALL_DIR"; install_completion "$INSTALL_DIR"; }

install_node_command() {
    colorized_echo blue "=============================="
    colorized_echo magenta "   Install OVNode   "
    colorized_echo blue "=============================="
    echo
    run_node_installer
}

main() {
    if [[ $# -eq 0 && -t 0 && "${YES:-0}" -eq 0 ]]; then
        render_banner "OVManager" "$VERSION"
        local choice
        choice="$(render_menu "" \
            install "Install OVManager" \
            update "Update OVManager" \
            status "Show status" \
            uninstall "Uninstall OVManager" \
            logs "Tail logs" \
            quit "Quit")"
        [[ "$choice" == "quit" ]] && return 0
        set -- "$choice"
    fi
    parse_args "$@"
    case "$ACTION" in
        version-script) print_version_script; return 0 ;;
        update) do_update "${UPDATE_ARGS[@]}" ;;
        status) do_status; return 0 ;;
        uninstall) do_uninstall "${UPDATE_ARGS[@]}"; return 0 ;;
        up) up_command; return 0 ;;
        down) down_command; return 0 ;;
        restart) restart_command; return 0 ;;
        logs) logs_command; return 0 ;;
        cli) shift; cli_command "$@"; return 0 ;;
        backup) shift; backup_command "$@"; return 0 ;;
        restore) shift; restore_command "$@"; return 0 ;;
        edit-env) edit_env_command; return 0 ;;
        install-script) install_script_command; return 0 ;;
        install-node) install_node_command; return 0 ;;
    esac
    if [[ "$FROM_SOURCE" -eq 1 ]]; then do_from_source; else do_install; fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
