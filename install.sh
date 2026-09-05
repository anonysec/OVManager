#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# OVManager installer — native (systemd) or Docker.
#
# Human (wizard, keeps your terminal as stdin):
#   bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh)
#
# AI / CI (never prompts; prints a plan then installs):
#   curl -sSL URL | sudo bash -s -- -y --mode native --admin-pass '…'
#   curl -sSL URL | sudo bash -s -- -y --mode docker --json
#
set -Eeuo pipefail

# Forks: point source downloads (and update pulls) at your own repo.
REPO="${OVM_REPO:-anonysec/OVManager}"
BRANCH="main"
INSTALL_DIR="/opt/ovmanager"
DATA_DIR="/var/lib/ovmanager"
DEFAULT_PORT=2095
DEFAULT_USER="admin"
SYSTEMD_SERVICE="ovmanager.service"
VERSION="2.0"

# ── Colour / TTY ───────────────────────────────────────────────────────
NC=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'
WH=$'\033[97m'; GR=$'\033[32m'; RD=$'\033[31m'
YL=$'\033[33m'; CY=$'\033[36m'; GY=$'\033[90m'
OR=$'\033[38;5;208m'
[[ -t 1 ]] || { NC=''; B=''; D=''; WH=''; GR=''; RD=''; YL=''; CY=''; GY=''; OR=''; }

line()  { printf '  %b\n' "$*" >&2; }
step()  { line "${GR}✓${NC}  $*"; }
info()  { line "${OR}→${NC}  $*"; }
warn()  { line "${YL}!${NC}  $*"; }
fail()  { line "${RD}✗${NC}  $*"; }
kv()    { printf '  %b%-14s%b %b\n' "$GY" "$1" "$NC" "$2" >&2; }
hr()    { line "${GY}──────────────────────────────────────────────${NC}"; }

die() { printf '\n  %bError:%b %s\n\n' "$RD" "$NC" "$1" >&2; exit 1; }
trap 'printf "\n  %bInterrupted.%b\n" "$RD" "$NC" >&2; exit 130' INT TERM

# ── Flags (defaults) ───────────────────────────────────────────────────
PORT="" PATHPREFIX="" ADMIN_USER="" ADMIN_PASS=""
TLS_MODE="" TLS_DOMAIN="" TLS_KEY="" TLS_CERT=""
PUBLIC_URL="" MODE="" ACTION="install"
YES=0 PURGE=0 JSON=0 DRY=0 GENERATED_PASS=0 PATH_SET=0
WANT_NODE=0 NODE_NAME="" NODE_KEY=""

[[ "${CI:-}" == "true" || "${NONINTERACTIVE:-}" == "1" ]] && YES=1

is_port() { [[ "$1" =~ ^[0-9]+$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )); }

rand_path() {
    openssl rand -hex 4 2>/dev/null || head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

rand_pass() {
    openssl rand -base64 18 2>/dev/null | tr -d '/+=\n' | head -c 20
}

fernet_key() {
    python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())' 2>/dev/null \
        || openssl rand -base64 32 | tr -d '\n'
}

# Interactive if the operator did not pass -y AND we can talk to a terminal.
# `curl | bash` has no stdin TTY; humans still work via /dev/tty.
# AI / CI must pass -y (or CI=true) so this never blocks on a prompt.
can_prompt() {
    [[ "$YES" -eq 0 ]] || return 1
    [[ -t 0 ]] && return 0
    [[ -e /dev/tty && -r /dev/tty ]] && return 0
    return 1
}

_read_reply() {  # hidden? → prints the line on stdout
    local hidden="${1:-}" buf=""
    if [[ -t 0 ]]; then
        if [[ "$hidden" == "h" ]]; then read -r -s buf; printf '\n' >&2; else read -r buf; fi
    elif [[ -e /dev/tty && -r /dev/tty ]]; then
        if [[ "$hidden" == "h" ]]; then read -r -s buf </dev/tty; printf '\n' >&2; else read -r buf </dev/tty; fi
    else
        return 1
    fi
    printf '%s' "$buf"
}

ask() {  # ask <label> <default> [hidden]
    local label="$1" default="$2" hidden="${3:-}" val=""
    if can_prompt; then
        printf '  %b%-18s%b %b[%s]%b : ' "$WH" "$label" "$NC" "$GY" "$default" "$NC" >&2
        val="$(_read_reply "$hidden")" || true
    fi
    [[ -n "$val" ]] || val="$default"
    printf '%s' "$val"
}

confirm() {
    [[ "$YES" -eq 1 ]] && return 0
    can_prompt || return 0
    printf '  %s [%bY%b/n] : ' "$1" "$GR" "$NC" >&2
    local c=""
    c="$(_read_reply)" || true
    [[ ! "$c" =~ ^[Nn]$ ]]
}

banner() {
    line ""
    line "${OR}╭──────────────────────────────────────────────╮${NC}"
    line "${OR}│${NC}  ${B}${WH}OVManager${NC}                                  ${OR}│${NC}"
    line "${OR}│${NC}  ${GY}OpenVPN panel installer${NC}  ${D}v${VERSION}${NC}          ${OR}│${NC}"
    line "${OR}╰──────────────────────────────────────────────╯${NC}"
    line ""
}

usage() {
    cat <<EOF
OVManager installer v${VERSION}

USAGE
  Human (wizard — keeps the terminal as stdin):
    bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh)

  AI / script (no prompts; flags or env vars):
    curl -sSL URL | sudo bash -s -- -y --mode native --admin-pass 'SECRET'
    curl -sSL URL | sudo bash -s -- -y --mode docker --json

COMMANDS
  install               Install (default)
  update                Pull, rebuild, restart (backs up data first)
  status                Show panel URL, health and version
  uninstall             Remove the app (data kept unless --purge)

MODE
  --mode native         systemd + uv + Node on the host          [default]
  --mode docker         Docker Engine, image built from source
  --docker              Alias for --mode docker

OPTIONS
  --port PORT           Panel port                               [2095]
  --path PATH           URL prefix (scanner-hiding). "root" = /
                        Default: random 8 hex chars
  --admin-user USER     Admin username                           [admin]
  --admin-pass PASS     Admin password (min 8). Generated if omitted
                        under -y / non-interactive
  --public-url URL      Canonical public origin for sub links
  --with-node [NAME]    Also print a ready OVNode one-liner for this server
                        (generates an API key; optional NAME, default node-1)
  --tls-none            Plain HTTP
  --tls-self            Self-signed certificate
  --tls-le DOMAIN       Let's Encrypt for a domain (needs :80)
  --tls-ip              Let's Encrypt short-lived cert for this IP
  --tls-custom KEY CERT Existing PEM key + cert
  --yes, -y             Never prompt. Required for AI / CI / pipes
  --non-interactive     Alias for --yes
  --json                Machine-readable result on stdout (logs on stderr)
  --dry-run             Resolve config, print the plan, change nothing
  --purge               uninstall: also delete data + certs
  --help, -h            This help

ENVIRONMENT  (used when the matching flag is omitted)
  OVM_MODE          native | docker
  OVM_PORT          port
  OVM_PATH          url path ("root" for /)
  OVM_ADMIN_USER    admin username
  OVM_ADMIN_PASS    admin password
  OVM_TLS           none | self | le | le-ip | custom
  OVM_TLS_DOMAIN    domain for --tls-le
  OVM_PUBLIC_URL    public origin
  OVM_WITH_NODE     1 to print a same-server OVNode one-liner (or a node name)
  CI=true           implies --yes
  NONINTERACTIVE=1  implies --yes

EXIT
  0 ok   1 error   2 already installed   130 interrupted

EOF
    exit 0
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --port)        [[ $# -ge 2 ]] || die "--port needs a value"; PORT="$2"; shift 2 ;;
            --path)        [[ $# -ge 2 ]] || die "--path needs a value"
                           PATHPREFIX="${2#/}"; PATHPREFIX="${PATHPREFIX%/}"
                           [[ "$PATHPREFIX" == "root" ]] && PATHPREFIX=""
                           PATH_SET=1
                           shift 2 ;;
            --admin-user)  [[ $# -ge 2 ]] || die "--admin-user needs a value"; ADMIN_USER="$2"; shift 2 ;;
            --admin-pass)  [[ $# -ge 2 ]] || die "--admin-pass needs a value"; ADMIN_PASS="$2"; shift 2 ;;
            --public-url)  [[ $# -ge 2 ]] || die "--public-url needs a value"; PUBLIC_URL="$2"; shift 2 ;;
            --with-node)
                WANT_NODE=1
                if [[ $# -ge 2 && "$2" != -* ]]; then NODE_NAME="$2"; shift 2; else shift; fi ;;
            --tls-le)      [[ $# -ge 2 ]] || die "--tls-le needs a domain"; TLS_MODE="le"; TLS_DOMAIN="$2"; shift 2 ;;
            --tls-ip)      TLS_MODE="le-ip"; shift ;;
            --tls-self)    TLS_MODE="self"; shift ;;
            --tls-custom)  [[ $# -ge 3 ]] || die "--tls-custom needs KEY CERT"
                           TLS_MODE="custom"; TLS_KEY="$2"; TLS_CERT="$3"; shift 3 ;;
            --tls-none)    TLS_MODE="none"; shift ;;
            --mode)        [[ $# -ge 2 ]] || die "--mode needs native or docker"; MODE="$2"; shift 2 ;;
            --docker)      MODE="docker"; shift ;;
            --yes|-y|--non-interactive) YES=1; shift ;;
            --json)        JSON=1; shift ;;
            --dry-run)     DRY=1; shift ;;
            --purge)       PURGE=1; shift ;;
            --uninstall)   ACTION="uninstall"; shift ;;
            --help|-h)     usage ;;
            install)       ACTION="install"; shift ;;
            update)        ACTION="update"; shift ;;
            status)        ACTION="status"; shift ;;
            uninstall)     ACTION="uninstall"; shift ;;
            *)             die "Unknown option: $1  (see --help)" ;;
        esac
    done
}

apply_env() {
    [[ -z "$MODE" && -n "${OVM_MODE:-}" ]] && MODE="$OVM_MODE"
    [[ -z "$PORT" && -n "${OVM_PORT:-}" ]] && PORT="$OVM_PORT"
    if [[ "$PATH_SET" -eq 0 && -n "${OVM_PATH:-}" ]]; then
        PATHPREFIX="${OVM_PATH#/}"; PATHPREFIX="${PATHPREFIX%/}"
        [[ "$PATHPREFIX" == "root" ]] && PATHPREFIX=""
        PATH_SET=1
    fi
    [[ -z "$ADMIN_USER" && -n "${OVM_ADMIN_USER:-}" ]] && ADMIN_USER="$OVM_ADMIN_USER"
    [[ -z "$ADMIN_PASS" && -n "${OVM_ADMIN_PASS:-}" ]] && ADMIN_PASS="$OVM_ADMIN_PASS"
    [[ -z "$TLS_MODE" && -n "${OVM_TLS:-}" ]] && TLS_MODE="$OVM_TLS"
    [[ -z "$TLS_DOMAIN" && -n "${OVM_TLS_DOMAIN:-}" ]] && TLS_DOMAIN="$OVM_TLS_DOMAIN"
    [[ -z "$PUBLIC_URL" && -n "${OVM_PUBLIC_URL:-}" ]] && PUBLIC_URL="$OVM_PUBLIC_URL"
    if [[ -z "$NODE_NAME" && -n "${OVM_WITH_NODE:-}" ]]; then
        WANT_NODE=1
        [[ "${OVM_WITH_NODE}" != "1" ]] && NODE_NAME="$OVM_WITH_NODE"
    fi
    if [[ -n "$MODE" ]]; then
        case "$MODE" in
            native|docker) ;;
            *) die "Invalid --mode '$MODE' (native | docker)" ;;
        esac
    fi
}

# ── OS ─────────────────────────────────────────────────────────────────
OS_ID="" OS_NAME="" PKG_INSTALL="" PKG_UPDATE=""

detect_os() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS_ID="${ID:-}"; OS_NAME="${PRETTY_NAME:-$OS_ID}"
    else
        die "Unsupported OS — no /etc/os-release."
    fi
    case "$OS_ID" in
        debian|ubuntu) PKG_UPDATE="apt-get update -qq"; PKG_INSTALL="apt-get install -y -qq" ;;
        rhel|centos|rocky|almalinux|fedora)
            if command -v dnf >/dev/null 2>&1; then
                PKG_UPDATE="dnf -q makecache"; PKG_INSTALL="dnf install -y -q"
            else
                PKG_UPDATE="yum -q makecache"; PKG_INSTALL="yum install -y -q"
            fi ;;
        arch)   PKG_UPDATE="pacman -Sy --noconfirm"; PKG_INSTALL="pacman -S --noconfirm" ;;
        alpine) PKG_UPDATE="apk update -q";          PKG_INSTALL="apk add -q" ;;
        *) die "Unsupported distribution: ${OS_ID:-unknown}" ;;
    esac
}

pkg_install() {
    info "Installing packages: $*"
    $PKG_UPDATE >/dev/null 2>&1 || true
    $PKG_INSTALL "$@" >/dev/null 2>&1 || die "Failed to install: $*  ($PKG_INSTALL $*)"
}

has_systemd() { command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; }

check_root() { [[ "$EUID" -eq 0 ]] || die "Must run as root (sudo)."; }

# ── Spinner / steps ────────────────────────────────────────────────────
run_step() {
    local msg="$1"; shift
    if [[ -t 1 ]]; then
        "$@" >/dev/null 2>&1 &
        local pid=$! chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏' i=0 rc=0
        while kill -0 "$pid" 2>/dev/null; do
            printf '\r  %b%s%b  %-46s' "$OR" "${chars:$((i % 10)):1}" "$NC" "$msg" >&2
            sleep 0.08; i=$((i + 1))
        done
        wait "$pid" 2>/dev/null || rc=$?
        printf '\r\033[K' >&2
        [[ $rc -eq 0 ]] && step "$msg" || { fail "$msg"; return 1; }
    else
        info "$msg"
        "$@" || { fail "$msg"; return 1; }
        step "$msg"
    fi
}

# ── Deps ───────────────────────────────────────────────────────────────
UV_BIN=""

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        UV_BIN="$(command -v uv)"; step "uv  $UV_BIN"; return
    fi
    info "Installing uv…"
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 \
        || python3 -m pip install --quiet uv >/dev/null 2>&1 \
        || die "Could not install uv. Manual: curl -LsSf https://astral.sh/uv/install.sh | sh"
    UV_BIN="$(command -v uv 2>/dev/null || true)"
    [[ -n "$UV_BIN" ]] || UV_BIN="$HOME/.local/bin/uv"
    [[ -x "$UV_BIN" ]] || die "uv not found after install"
    step "uv  $UV_BIN"
}

ensure_node() {
    if command -v node >/dev/null 2>&1; then
        local maj; maj="$(node -v 2>/dev/null | sed 's/^v//;s/\..*//')"
        if [[ -n "$maj" ]] && (( maj < 20 )); then
            warn "Node.js $(node -v) — Vite 7 wants >= 20.19; install Node 22 LTS"
        fi
        command -v npm >/dev/null 2>&1 || pkg_install npm
        step "Node.js $(node -v)"
        return
    fi
    info "Installing Node.js 22 LTS…"
    case "$OS_ID" in
        debian|ubuntu)
            curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1 \
                && pkg_install nodejs \
                || die "Could not install Node.js from NodeSource"
            ;;
        *) pkg_install nodejs npm ;;
    esac
    command -v node >/dev/null 2>&1 || die "Node.js installation failed"
    step "Node.js $(node -v)"
}

ensure_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        info "Installing Docker Engine…"
        if [[ "$PKG_INSTALL" == apt* ]]; then
            $PKG_UPDATE >/dev/null 2>&1 || true
            $PKG_INSTALL docker.io >/dev/null 2>&1 \
                || $PKG_INSTALL docker-ce >/dev/null 2>&1 \
                || die "Could not install Docker. https://docs.docker.com/engine/install/"
        else
            pkg_install docker docker-compose-plugin 2>/dev/null || pkg_install docker
        fi
        command -v docker >/dev/null 2>&1 || die "Docker binary not found"
    fi
    docker compose version >/dev/null 2>&1 \
        || command -v docker-compose >/dev/null 2>&1 \
        || die "Docker Compose v2 is required (docker compose plugin)"
    step "Docker  $(docker --version 2>/dev/null | head -1)"
}

check_deps() {
    local missing=()
    for cmd in curl tar openssl git python3; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    [[ ${#missing[@]} -eq 0 ]] || pkg_install "${missing[@]}"
    step "System tools present"
}

# ── Backup / firewall / health ─────────────────────────────────────────
backup_dir() {
    local src="$1" label="$2"
    [[ -d "$src" ]] || return 0
    mkdir -p /var/backups
    local stamp base file
    stamp="$(date +%Y%m%d-%H%M%S)"
    base="$(basename "$src")"
    file="/var/backups/${label}-${base}-${stamp}.tar.gz"
    info "Backup ${label} → $file"
    tar -czf "$file" -C "$(dirname "$src")" "$base" 2>/dev/null \
        || warn "Backup failed for $src — continuing"
    [[ -f "$file" ]] && step "Backup  $file"
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

# ── TLS ────────────────────────────────────────────────────────────────
generate_self_signed() {
    info "Self-signed certificate…"
    mkdir -p /etc/ssl/self-signed
    local cn; cn="$(hostname -I 2>/dev/null | awk '{print $1}')"
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout /etc/ssl/self-signed/privkey.pem \
        -out /etc/ssl/self-signed/fullchain.pem \
        -subj "/C=US/ST=Local/L=Local/O=OVManager/CN=${cn}" >/dev/null 2>&1
    # The Docker image runs as appuser (uid 1000) with these files mounted
    # read-only — they must be world-readable or the panel crash-loops.
    chmod 644 /etc/ssl/self-signed/privkey.pem /etc/ssl/self-signed/fullchain.pem
    TLS_KEY="/etc/ssl/self-signed/privkey.pem"
    TLS_CERT="/etc/ssl/self-signed/fullchain.pem"
    step "Certificate  $TLS_CERT"
}

ensure_acme() {
    [[ -x "$HOME/.acme.sh/acme.sh" ]] && return 0
    info "Installing acme.sh…"
    curl -s https://get.acme.sh | sh >/dev/null 2>&1 || die "Failed to install acme.sh"
}

issue_lets_encrypt() {
    local domain="$1" is_ip="$2"
    ensure_acme
    local email="acme-$(openssl rand -hex 4)@example.com"
    local outdir="/etc/letsencrypt/$domain"
    mkdir -p "$outdir"
    if [[ -f "$outdir/fullchain.pem" ]]; then
        local expiry days_left=0
        expiry="$(openssl x509 -enddate -noout -in "$outdir/fullchain.pem" 2>/dev/null | cut -d= -f2)"
        days_left=$(( ($(date -d "$expiry" +%s 2>/dev/null || echo 0) - $(date +%s)) / 86400 ))
        if (( days_left > 7 )); then
            step "Existing certificate valid ${days_left}d"
            return 0
        fi
        warn "Certificate expires in ${days_left}d — renewing"
    fi
    local extra_args=()
    if [[ "$is_ip" == "1" ]]; then
        info "Short-lived certificate for IP $domain…"
        extra_args=(--certificate-profile shortlived --days 6)
    else
        info "Let's Encrypt for $domain…"
    fi
    "$HOME/.acme.sh/acme.sh" --issue -d "$domain" --standalone "${extra_args[@]}" \
        --accountemail "$email" >/dev/null 2>&1 \
        || die "Failed to issue Let's Encrypt certificate for $domain"
    "$HOME/.acme.sh/acme.sh" --install-cert -d "$domain" \
        --key-file "$outdir/privkey.pem" \
        --fullchain-file "$outdir/fullchain.pem" \
        --reloadcmd "chmod 644 $outdir/privkey.pem $outdir/fullchain.pem; systemctl restart $SYSTEMD_SERVICE >/dev/null 2>&1 || docker restart ovmanager >/dev/null 2>&1 || true" \
        >/dev/null 2>&1 || die "Failed to install certificate to $outdir"
    # Docker appuser (uid 1000) reads these via a read-only mount (renewals
    # re-apply perms through the reloadcmd above).
    chmod 644 "$outdir/privkey.pem" "$outdir/fullchain.pem"
    step "Certificate  $outdir"
}

port_in_use() { ss -ltn 2>/dev/null | awk -v p=":${1}$" '$4 ~ p {exit 0} END {exit 1}'; }

setup_tls() {
    case "$TLS_MODE" in
        le)
            port_in_use 80 && die "Port 80 is busy — Let's Encrypt standalone needs it"
            issue_lets_encrypt "$TLS_DOMAIN" "0"
            TLS_KEY="/etc/letsencrypt/$TLS_DOMAIN/privkey.pem"
            TLS_CERT="/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem"
            ;;
        le-ip)
            port_in_use 80 && die "Port 80 is busy — Let's Encrypt standalone needs it"
            TLS_DOMAIN="${TLS_DOMAIN:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
            issue_lets_encrypt "$TLS_DOMAIN" "1"
            TLS_KEY="/etc/letsencrypt/$TLS_DOMAIN/privkey.pem"
            TLS_CERT="/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem"
            ;;
        self) generate_self_signed ;;
        custom)
            [[ -f "$TLS_KEY" && -f "$TLS_CERT" ]] || die "Custom key/cert not found: $TLS_KEY $TLS_CERT"
            local out="/etc/letsencrypt/${TLS_DOMAIN:-panel}"
            mkdir -p "$out"
            cp "$TLS_KEY" "$out/privkey.pem"
            cp "$TLS_CERT" "$out/fullchain.pem"
            chmod 644 "$out/privkey.pem" "$out/fullchain.pem"  # Docker appuser reads via ro mount
            TLS_KEY="$out/privkey.pem"; TLS_CERT="$out/fullchain.pem"
            ;;
        none) ;;
        *) die "Invalid TLS mode: '$TLS_MODE'" ;;
    esac
}

# ── Source / env ───────────────────────────────────────────────────────
fetch_source() {
    if command -v git >/dev/null 2>&1; then
        run_step "Cloning ${REPO}@${BRANCH}" \
            git clone --depth 1 --branch "$BRANCH" "https://github.com/${REPO}.git" "$INSTALL_DIR"
    else
        run_step "Downloading source tarball" \
            curl -sSLo /tmp/ovm.tar.gz "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
        mkdir -p "$INSTALL_DIR"
        tar -xzf /tmp/ovm.tar.gz --strip-components=1 -C "$INSTALL_DIR" \
            || die "Extract failed"
        rm -f /tmp/ovm.tar.gz
        step "Source extracted"
    fi
}

write_env() {
    local jwt bot
    jwt="$(openssl rand -base64 48 2>/dev/null | tr -d '\n')"
    bot="$(fernet_key)"
    # In Docker mode the .env is consumed INSIDE the container, where the
    # data dir is the /app/data mount — never the host path (writing the
    # host path here made fresh Docker installs crash-loop with
    # PermissionError as appuser). Native mode keeps the host path.
    local data_dir="$DATA_DIR"
    [[ "$MODE" == "docker" ]] && data_dir="/app/data"
    umask 077
    {
        printf 'HOST=0.0.0.0\n'
        printf 'PORT=%s\n' "$PORT"
        printf 'URLPATH=%s\n' "$PATHPREFIX"
        printf 'ADMIN_USERNAME=%s\n' "$ADMIN_USER"
        printf 'ADMIN_PASSWORD=%s\n' "$ADMIN_PASS"
        printf 'JWT_SECRET_KEY=%s\n' "$jwt"
        printf 'DATA_DIR=%s\n' "$data_dir"
        [[ -n "$PUBLIC_URL" ]] && printf 'PUBLIC_URL=%s\n' "$PUBLIC_URL"
        [[ -n "$bot" ]] && printf 'BOT_ENCRYPT_KEY=%s\n' "$bot"
        [[ -n "$TLS_KEY" ]] && printf 'SSL_KEYFILE=%s\n' "$TLS_KEY"
        [[ -n "$TLS_CERT" ]] && printf 'SSL_CERTFILE=%s\n' "$TLS_CERT"
    } > "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    step "Config  $INSTALL_DIR/.env"
}

read_env_port() {
    [[ -f "$INSTALL_DIR/.env" ]] || return 0
    local p
    p="$(awk -F= '/^PORT=/{print $2; exit}' "$INSTALL_DIR/.env" | tr -d '\r')"
    [[ -n "$p" ]] && PORT="${PORT:-$p}"
    local t
    t="$(awk -F= '/^SSL_KEYFILE=/{print $2; exit}' "$INSTALL_DIR/.env" | tr -d '\r')"
    if [[ -n "$t" && -z "$TLS_MODE" ]]; then TLS_MODE="self"; fi
}

# ── Native ─────────────────────────────────────────────────────────────
write_systemd_unit() {
    cat > "/etc/systemd/system/$SYSTEMD_SERVICE" << UNIT
[Unit]
Description=OVManager OpenVPN Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="DATA_DIR=${DATA_DIR}"
ExecStart=${UV_BIN} run main.py
Restart=on-failure
RestartSec=3
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload >/dev/null 2>&1
    systemctl enable "$SYSTEMD_SERVICE" >/dev/null 2>&1
    step "systemd  $SYSTEMD_SERVICE"
}

build_frontend() {
    [[ -f "$INSTALL_DIR/frontend/package.json" ]] || return 0
    cd "$INSTALL_DIR/frontend"
    run_step "Node.js dependencies" npm ci --no-audit --no-fund
    run_step "Frontend build" npm run build
}

# ── Docker ─────────────────────────────────────────────────────────────
COMPOSE_FILE="$DATA_DIR/ovmanager-compose.yml"

write_compose() {
    mkdir -p "$DATA_DIR"
    # The image runs as appuser (uid 1000); a root-owned host dir would
    # make the container crash-loop on first DB write (the mount masks
    # the prepared /app/data). Match Dockerfile's `useradd -u 1000`.
    chown -R 1000:1000 "$DATA_DIR"
    cat > "$COMPOSE_FILE" << COMPOSE
services:
  ovmanager:
    build:
      context: ${INSTALL_DIR}
      dockerfile: Dockerfile
    container_name: ovmanager
    restart: unless-stopped
    ports:
      - "${PORT}:${PORT}"
    env_file:
      - ${INSTALL_DIR}/.env
    volumes:
      - ${DATA_DIR}:/app/data
      - /etc/letsencrypt:/etc/letsencrypt:ro
      - /etc/ssl/self-signed:/etc/ssl/self-signed:ro
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import socket; socket.create_connection(('127.0.0.1', ${PORT}), 3)\""]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 25s
COMPOSE
    step "Compose  $COMPOSE_FILE"
}

compose_up() {
    write_compose
    info "Building image (first run takes a few minutes)…"
    # BuildKit progress goes to stdout — keep the --json contract (exactly
    # one JSON object on stdout, logs on stderr) by sinking it otherwise.
    if [[ "$JSON" -eq 1 ]]; then
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" up -d --build >/dev/stderr ) \
            || die "docker compose up failed — docker logs ovmanager"
    else
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" up -d --build ) \
            || die "docker compose up failed — docker logs ovmanager"
    fi
    step "Container  ovmanager"
}

# ── Validate / wizard / plan ───────────────────────────────────────────
validate_input() {
    is_port "$PORT" || die "Invalid port: '$PORT'"
    [[ -n "$ADMIN_USER" ]] || ADMIN_USER="$DEFAULT_USER"
    [[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,64}$ ]] || die "Admin username: 3–64 letters, digits, . _ -"
    if [[ -z "$ADMIN_PASS" ]]; then
        ADMIN_PASS="$(rand_pass)"
        GENERATED_PASS=1
        [[ ${#ADMIN_PASS} -ge 8 ]] || die "Could not generate an admin password"
        warn "No password given — generated one (shown at the end)"
    fi
    [[ ${#ADMIN_PASS} -ge 8 ]] || die "Admin password must be at least 8 characters"
    if [[ -n "$PATHPREFIX" ]]; then
        [[ "$PATHPREFIX" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "URL path: letters, digits, dash, underscore"
    fi
    if [[ "$WANT_NODE" -eq 1 ]]; then
        [[ -n "$NODE_NAME" ]] || NODE_NAME="node-1"
        [[ "$NODE_NAME" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "Node name: 1–64 letters, digits, dash, underscore"
        [[ ${#NODE_KEY} -ge 16 ]] || die "Node API key must be at least 16 characters"
    fi
    case "$TLS_MODE" in
        le)
            [[ -n "$TLS_DOMAIN" ]] || die "--tls-le needs a domain" ;;
        le-ip|self|custom|none) ;;
        *) die "Invalid TLS mode: '$TLS_MODE'" ;;
    esac
    if [[ "$TLS_MODE" == "custom" ]]; then
        [[ -f "$TLS_KEY" && -f "$TLS_CERT" ]] || die "Custom TLS files not found"
    fi
}

wizard() {
    if [[ -z "$MODE" ]]; then
        line "${B}Install mode${NC}"
        line "  ${WH}1${NC}  Native     systemd service, uv + Node on this host"
        line "  ${WH}2${NC}  Docker     container image, Docker Engine on this host"
        local m
        m="$(ask "Mode" "1")"
        case "${m:-1}" in
            2|docker|Docker) MODE="docker" ;;
            *)               MODE="native" ;;
        esac
        line ""
    fi
    PORT="$(ask "Port" "${PORT:-$DEFAULT_PORT}")"
    local path_default="random"
    [[ "$PATH_SET" -eq 1 ]] && path_default="${PATHPREFIX:-root}"
    local path_in
    path_in="$(ask "URL path  (random / root / name)" "$path_default")"
    case "$path_in" in
        root|"/") PATHPREFIX="" ;;
        random|"") PATHPREFIX="$(rand_path)" ;;
        *) PATHPREFIX="${path_in#/}"; PATHPREFIX="${PATHPREFIX%/}" ;;
    esac
    ADMIN_USER="$(ask "Admin user" "${ADMIN_USER:-$DEFAULT_USER}")"
    if [[ -z "$ADMIN_PASS" ]]; then
        ADMIN_PASS="$(ask "Admin pass" "" "h")"
    fi
    if [[ -z "$TLS_MODE" ]]; then
        line ""
        line "${B}TLS — encrypts your login and the panel${NC}"
        line "  ${WH}1${NC}  Let's Encrypt (domain)     needs a domain pointed here + free port 80"
        line "  ${WH}2${NC}  Let's Encrypt (this IP)    short-lived cert, no domain needed"
        line "  ${WH}3${NC}  Self-signed                encrypted; browser shows one warning to click through"
        line "  ${WH}4${NC}  Custom key + cert          you already have PEM files"
        line "  ${WH}5${NC}  None — HTTP only           fine on a private network, unsafe on the internet"
        local tls
        tls="$(ask "TLS" "3")"
        case "${tls:-3}" in
            1) TLS_MODE="le"; TLS_DOMAIN="$(ask "Domain" "${TLS_DOMAIN:-}")"
               [[ -n "$TLS_DOMAIN" ]] || die "Domain required for Let's Encrypt" ;;
            2) TLS_MODE="le-ip"; TLS_DOMAIN="$(hostname -I 2>/dev/null | awk '{print $1}')" ;;
            3) TLS_MODE="self" ;;
            4) TLS_MODE="custom"; TLS_KEY="$(ask "Key file" "")"; TLS_CERT="$(ask "Cert file" "")" ;;
            *) TLS_MODE="none" ;;
        esac
    fi
    if [[ "$WANT_NODE" -eq 0 ]]; then
        line ""
        if confirm "Also run a VPN node on THIS server? (easiest setup)"; then
            WANT_NODE=1
        fi
    fi
    if [[ "$WANT_NODE" -eq 1 ]]; then
        [[ -n "$NODE_NAME" ]] || NODE_NAME="$(ask "Node name" "node-1")"
        [[ "$NODE_NAME" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "Node name: 1–64 letters, digits, dash, underscore"
        if [[ -z "$NODE_KEY" ]]; then
            NODE_KEY="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
            [[ ${#NODE_KEY} -ge 16 ]] || die "Could not generate a node API key"
        fi
    fi
}

print_plan() {
    hr
    kv "OS"      "$OS_NAME"
    kv "Mode"    "${B}${MODE}${NC}"
    kv "Port"    "$PORT"
    kv "URL path" "$( [[ -n "$PATHPREFIX" ]] && printf '/%s/' "$PATHPREFIX" || printf '/' )"
    kv "Admin"   "$ADMIN_USER"
    kv "TLS"     "$TLS_MODE"
    if [[ "$WANT_NODE" -eq 1 ]]; then
        kv "Node" "same server as '${NODE_NAME}' (one-liner printed at the end)"
    fi
    kv "Install" "$INSTALL_DIR"
    kv "Data"    "$DATA_DIR"
    if [[ "$TLS_MODE" == "none" ]]; then
        warn "TLS off — login travels in plaintext. Use --tls-self / --tls-le on the public internet."
    fi
    hr
}

emit_json() {
    local ok="$1" url
    url="$(panel_url)"
    python3 - "$ok" "$MODE" "$url" "$ADMIN_USER" "$ADMIN_PASS" "$INSTALL_DIR" "$DATA_DIR" "$TLS_MODE" "$PORT" "$PATHPREFIX" "$GENERATED_PASS" "$WANT_NODE" "$NODE_NAME" "$NODE_KEY" <<'PY'
import json, sys
(ok, mode, url, user, password, install, data, tls, port,
 path, gen, want_node, node_name, node_key) = sys.argv[1:]
out = {
    "ok": ok == "1",
    "mode": mode,
    "url": url,
    "user": user,
    "password": password,
    "password_generated": gen == "1",
    "port": int(port),
    "path": path,
    "tls": tls,
    "install_dir": install,
    "data_dir": data,
}
if want_node == "1":
    out["node"] = {"name": node_name, "api_key": node_key, "same_server": True}
print(json.dumps(out, ensure_ascii=False, indent=2))
PY
}

success_card() {
    local url manage logs
    url="$(panel_url)"
    if [[ "$MODE" == "docker" ]]; then
        manage="docker ps --filter name=ovmanager"
        logs="docker logs -f ovmanager"
    else
        manage="systemctl status ${SYSTEMD_SERVICE}"
        logs="journalctl -u ${SYSTEMD_SERVICE} -f"
    fi
    line ""
    line "${GR}╭──────────────────────────────────────────────╮${NC}"
    line "${GR}│${NC}  ${B}Ready${NC}                                     ${GR}│${NC}"
    line "${GR}╰──────────────────────────────────────────────╯${NC}"
    line ""
    kv "Open"   "${WH}${url}${NC}"
    kv "Login"  "${GR}${ADMIN_USER}${NC}"
    if [[ "$GENERATED_PASS" -eq 1 ]]; then
        kv "Password" "${YL}${ADMIN_PASS}${NC}  ${GY}(generated — save this)${NC}"
    else
        kv "Password" "${GY}(the one you set)${NC}"
    fi
    kv "Manage" "$manage"
    kv "Logs"   "$logs"
    kv "Data"   "$DATA_DIR"
    line ""
    if [[ "$WANT_NODE" -eq 1 ]]; then
        info "Step 2 — run this ON THIS SERVER to add your first VPN node:"
        line ""
        line "  ${WH}curl -sSL https://anonysec.github.io/OVNode/install.sh \\${NC}"
        line "    ${WH}| sudo bash -s -- install -y --name '${NODE_NAME}' --tls selfsigned \\${NC}"
        line "      ${WH}--api-key '${NODE_KEY}'${NC}"
        line ""
        info "Then in the panel: Nodes → Add Node (name '${NODE_NAME}', address 127.0.0.1,"
        info "port 2083, TLS on). Separate server instead? See docs/multi-node.md."
    else
        info "Next: install an OVNode, then Nodes → Add Node in the panel."
        info "Same server is easiest — re-run with --with-node to get a ready command."
    fi
    line ""
}

# ── Actions ────────────────────────────────────────────────────────────
do_install() {
    [[ -d "$INSTALL_DIR" ]] && die "Already installed ($INSTALL_DIR). Use: $0 update"
    mkdir -p "$DATA_DIR"

    hr; info "Downloading OVManager ($BRANCH)"
    fetch_source

    setup_tls
    write_env

    local scheme; scheme="$(scheme_of)"

    if [[ "$MODE" == "docker" ]]; then
        compose_up
    else
        has_systemd || die "systemd not found — native install needs it (use --mode docker)"
        info "Python dependencies (uv sync)…"
        cd "$INSTALL_DIR"
        run_step "Python packages" "$UV_BIN" sync --quiet
        build_frontend
        write_systemd_unit
        run_step "Service started" systemctl restart "$SYSTEMD_SERVICE"
    fi

    wait_health "${scheme}://127.0.0.1:${PORT}/health" 40 \
        || warn "No answer on /health yet — check logs"

    info "Finalizing first-boot…"
    if [[ "$MODE" == "docker" ]]; then
        docker restart ovmanager >/dev/null 2>&1 || true
    else
        systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
    fi
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 40 \
        || warn "No answer on /health after finalize"
    open_firewall_port "$PORT"
    success_card
    [[ "$JSON" -eq 1 ]] && emit_json 1
}

do_update() {
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    info "Updating OVManager…"
    [[ -f "$COMPOSE_FILE" ]] && MODE="docker"
    read_env_port
    : "${PORT:=$DEFAULT_PORT}"
    : "${TLS_MODE:=none}"
    if [[ "$MODE" == "docker" ]]; then
        ensure_docker
    else
        ensure_uv
        ensure_node
    fi
    backup_dir "$DATA_DIR" "panel"
    cd "$INSTALL_DIR"
    if [[ -d .git ]]; then
        git stash --quiet 2>/dev/null || true
        run_step "Pull ${BRANCH}" git pull --rebase origin "$BRANCH"
        git stash pop --quiet 2>/dev/null || true
    else
        warn "No git checkout — re-downloading source (.env + data kept)"
        run_step "Downloading source" \
            curl -sSLo /tmp/ovm.tar.gz "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
        tar -xzf /tmp/ovm.tar.gz --strip-components=1 -C "$INSTALL_DIR" || die "Extract failed"
        rm -f /tmp/ovm.tar.gz
    fi
    local scheme; scheme="$(scheme_of)"
    if [[ "$MODE" == "docker" ]]; then
        compose_up
    else
        run_step "Python packages" "$UV_BIN" sync --quiet
        build_frontend
        run_step "Service restarted" systemctl restart "$SYSTEMD_SERVICE"
    fi
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 60 \
        || warn "No answer on /health — check logs"
    step "Update complete"
    line ""
    [[ "$JSON" -eq 1 ]] && emit_json 1
}

do_status() {
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    read_env_port
    : "${PORT:=$DEFAULT_PORT}"
    # Panel path prefix as written at install time (.env). If it was changed
    # later in Settings → General, the live value lives in the DB instead.
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        PATHPREFIX="$(awk -F= '/^URLPATH=/{print $2; exit}' "$INSTALL_DIR/.env" | tr -d '\r')"
    fi
    local scheme url mode health ver
    scheme="$(scheme_of)"
    if [[ -f "$COMPOSE_FILE" ]]; then mode="docker"; else mode="native"; fi
    url="$(panel_url)"
    if wait_health "${scheme}://127.0.0.1:${PORT}/health" 5; then
        health="ok"
    else
        health="unreachable (check logs)"
    fi
    ver="$(curl -fskS --max-time 3 "${scheme}://127.0.0.1:${PORT}/health" 2>/dev/null \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version","?"))' 2>/dev/null || echo "?")"
    hr
    kv "Installed" "yes ($INSTALL_DIR)"
    kv "Mode"      "$mode"
    kv "Open"      "$url"
    kv "Health"    "$health"
    kv "Version"   "$ver"
    kv "Data"      "$DATA_DIR"
    hr
    if [[ "$JSON" -eq 1 ]]; then
        python3 - "$mode" "$url" "$health" "$ver" "$INSTALL_DIR" "$DATA_DIR" "$PORT" <<'PY'
import json, sys
mode, url, health, ver, install, data, port = sys.argv[1:]
print(json.dumps({
    "ok": health == "ok",
    "installed": True,
    "mode": mode,
    "url": url,
    "health": health,
    "version": ver,
    "install_dir": install,
    "data_dir": data,
    "port": int(port),
}, ensure_ascii=False, indent=2))
PY
    fi
}

do_uninstall() {
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    if [[ "$DRY" -eq 1 ]]; then
        info "Dry run — nothing changed (would stop the service and remove $INSTALL_DIR)."
        exit 0
    fi
    confirm "Remove OVManager and stop the service?" || die "Cancelled."
    systemctl stop "$SYSTEMD_SERVICE" 2>/dev/null || true
    systemctl disable "$SYSTEMD_SERVICE" 2>/dev/null || true
    rm -f "/etc/systemd/system/$SYSTEMD_SERVICE"
    systemctl daemon-reload 2>/dev/null || true
    if command -v docker >/dev/null 2>&1 && [[ -f "$COMPOSE_FILE" ]]; then
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" down ) >/dev/null 2>&1 || true
        docker rm -f ovmanager >/dev/null 2>&1 || true
    fi
    rm -rf "$INSTALL_DIR"
    if [[ "$PURGE" -eq 1 ]]; then
        backup_dir "$DATA_DIR" "panel-pre-purge"
        rm -rf "$DATA_DIR"
        step "Data removed"
    else
        step "App removed. Data kept at $DATA_DIR  (--purge to delete)"
    fi
    step "Uninstalled"
    line ""
}

already_installed_menu() {
    warn "OVManager is already at $INSTALL_DIR"
    if [[ "$DRY" -eq 1 ]]; then
        info "Dry run — nothing changed (re-run without --dry-run to update/uninstall)."
        exit 0
    fi
    if can_prompt; then
        line ""
        line "  ${GR}1${NC}  Update to latest"
        line "  ${YL}2${NC}  Uninstall"
        line "  ${GY}3${NC}  Quit"
        line ""
        local choice; choice="$(ask "Select" "3")"
        case "${choice:-3}" in
            1) ACTION="update"; check_root; do_update ;;
            2) ACTION="uninstall"; check_root; do_uninstall ;;
            *) exit 0 ;;
        esac
    else
        fail "Already installed. Re-run with:  $0 update"
        exit 2
    fi
}

# ── Main ───────────────────────────────────────────────────────────────
main() {
    parse_args "$@"
    apply_env
    if can_prompt && [[ "$JSON" -eq 0 ]]; then
        command clear >/dev/null 2>&1 || true
    fi
    banner

    # Root is required only for paths that change the system. Dry runs
    # (plan/validate/print only — every DRY branch exits before mutating
    # anything) and the already-installed guard (refuse/quit paths) must
    # work for anyone, including CI sandboxes and non-root operators.
    case "$ACTION" in
        uninstall) [[ "$DRY" -eq 0 ]] && check_root; do_uninstall; exit 0 ;;
        status) check_root; detect_os; do_status; exit 0 ;;
        update)
            detect_os
            if [[ "$DRY" -eq 1 ]]; then
                info "Dry run — nothing changed (would back up data, pull, rebuild)."
                exit 0
            fi
            check_root
            [[ "$YES" -eq 1 ]] || confirm "Update OVManager now?" || exit 0
            check_deps
            do_update
            exit 0
            ;;
    esac

    if [[ -d "$INSTALL_DIR" ]]; then
        already_installed_menu
        exit 0
    fi
    [[ "$DRY" -eq 0 ]] && check_root

    detect_os

    if can_prompt && [[ "$YES" -eq 0 ]]; then
        wizard
    else
        : "${PORT:=$DEFAULT_PORT}"
        if [[ "$PATH_SET" -eq 0 ]]; then
            PATHPREFIX="$(rand_path)"
        fi
        : "${ADMIN_USER:=$DEFAULT_USER}"
        : "${TLS_MODE:=none}"
        : "${MODE:=native}"
        if [[ "$WANT_NODE" -eq 1 ]]; then
            : "${NODE_NAME:=node-1}"
            if [[ -z "$NODE_KEY" ]]; then
                NODE_KEY="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
            fi
        fi
        info "Non-interactive  mode=${MODE}  port=${PORT}  tls=${TLS_MODE}"
    fi
    validate_input
    print_plan

    if [[ "$DRY" -eq 1 ]]; then
        info "Dry run — nothing changed."
        [[ "$JSON" -eq 1 ]] && emit_json 1
        exit 0
    fi

    # Preflight BEFORE asking to proceed or downloading anything: fail fast
    # with a fix hint instead of after minutes of setup.
    if [[ "$MODE" == "native" ]] && ! has_systemd; then
        die "systemd not found — native install needs it (use --mode docker on WSL/containers)"
    fi
    if port_in_use "$PORT"; then
        die "Port $PORT is already in use — pick another with --port PORT"
    fi
    if [[ "$TLS_MODE" == "le" || "$TLS_MODE" == "le-ip" ]] && port_in_use 80; then
        die "Port 80 is busy — Let's Encrypt standalone needs it (or use --tls-self for now)"
    fi

    confirm "Proceed with ${MODE} install?" || die "Cancelled."
    check_deps
    if [[ "$MODE" == "docker" ]]; then
        ensure_docker
    else
        ensure_uv
        ensure_node
    fi
    do_install
}

main "$@"
