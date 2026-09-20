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
# Where the code comes from: "release" (default) downloads the versioned
# prebuilt tarball from GitHub Releases (no git/npm needed on the server);
# "source" clones/pulls git and builds the frontend (developers).
SRC="${OVM_SRC:-release}"
INSTALL_DIR="/opt/ovmanager"
DATA_DIR="/var/lib/ovmanager"
DEFAULT_PORT=2095
DEFAULT_USER="admin"
SYSTEMD_SERVICE="ovmanager.service"
VERSION="1.2.3"
# Terminal command installed by install_cli() (copy of the manager).
BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"
CLI_NAME="ovmanager"
CLI_ALIAS="ovm"

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
# CLI_GIVEN: any flag/command was passed (as opposed to a bare run → menu).
# EXPRESS: the start menu's zero-questions install preset is active.
CLI_GIVEN=0 EXPRESS=0

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
    # /dev/tty can exist but be unopenable (containers, detached shells):
    # actually try to open it, or prompts silently fall back to defaults.
    { : </dev/tty; } 2>/dev/null && return 0
    return 1
}

# Stronger check for the interactive menu: stdin must be a real terminal or
# an openable /dev/tty. Scripts and pipes take the subcommand path instead.
has_tty() {
    [[ -t 0 ]] && return 0
    { : </dev/tty; } 2>/dev/null && return 0
    return 1
}

# Masked input: prints one * per character on stderr, backspace works, and
# the value goes to stdout (never echoed as plain text). Reads stdin, so
# callers redirect /dev/tty when needed.
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

# Explicit-yes prompt (default NO): used for destructive extras like deleting
# data during uninstall. Non-interactive runs keep the safe answer.
confirm_no() {
    [[ "$YES" -eq 1 ]] && return 1
    can_prompt || return 1
    printf '  %s [y/%bN%b] : ' "$1" "$GR" "$NC" >&2
    local c=""
    c="$(_read_reply)" || true
    [[ "$c" =~ ^[Yy]$ ]]
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
  Human (menu — keeps the terminal as stdin):
    bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh)
    Menu: 1) Express (one question)  2) Custom (every option)

  AI / script (no prompts; flags or env vars):
    curl -sSL URL | sudo bash -s -- -y --mode native --admin-pass 'SECRET'

COMMANDS  (default: install)
  update                Fetch release (or pull), rebuild if needed, restart
                        (backs up data first)
  uninstall [--purge]   Remove the app (data kept unless --purge)

  Everything else (status, logs, backup, TLS, recovery) lives in the
  manager: ovm  (installed as ovmanager/ovm).

MODE
  --mode native|docker  systemd + uv + Node, or Docker Engine  [native]

SOURCE
  --from-release        Download the versioned release file      [default]
                        (prebuilt frontend, verified checksum)
  --from-source         Clone/pull git and build locally (developers)

TLS  (numbers; wizard asks when omitted)
  --tls 1               Self-signed certificate                  [default]
  --tls 2 --tls-domain DOMAIN   Let's Encrypt for a domain (needs :80)
  --tls 3               Let's Encrypt short-lived cert for this IP
  --tls 4 --tls-key KEY --tls-cert CERT   Existing PEM key + cert

OPTIONS
  --admin-pass PASS     Admin password (min 12, not a common word).
                        Generated if omitted under -y / non-interactive
  --yes, -y             Never prompt. Required for AI / CI / pipes
  --json                Machine-readable result on stdout (logs on stderr)
  --dry-run             Resolve config, print the plan, change nothing
  --purge               uninstall: also delete data + certs
  --help, -h            This help

ENVIRONMENT  (used when the matching flag is omitted)
  OVM_MODE          native | docker
  OVM_SRC           release | source  (default: release)
  OVM_ADMIN_PASS    admin password
  OVM_PORT / OVM_PATH / OVM_ADMIN_USER / OVM_TLS / OVM_TLS_DOMAIN /
  OVM_PUBLIC_URL    advanced overrides (the wizard asks instead)
  CI=true           implies --yes
  NONINTERACTIVE=1  implies --yes

EXIT
  0 ok   1 error   2 already installed   130 interrupted

EOF
    exit 0
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        CLI_GIVEN=1
        case "$1" in
            --admin-pass)  [[ $# -ge 2 ]] || die "--admin-pass needs a value"; ADMIN_PASS="$2"; shift 2 ;;
            --mode)        [[ $# -ge 2 ]] || die "--mode needs native or docker"; MODE="$2"; shift 2 ;;
            --tls)         [[ $# -ge 2 ]] || die "--tls needs 1, 2, 3 or 4 (see --help)"
                            case "$2" in
                                1) TLS_MODE="self" ;;
                                2) TLS_MODE="le" ;;
                                3) TLS_MODE="le-ip" ;;
                                4) TLS_MODE="custom" ;;
                                *) die "--tls needs 1, 2, 3 or 4 (see --help)" ;;
                            esac
                            shift 2 ;;
            --tls-domain)  [[ $# -ge 2 ]] || die "--tls-domain needs a domain"; TLS_DOMAIN="$2"; shift 2 ;;
            --tls-key)     [[ $# -ge 2 ]] || die "--tls-key needs a file"; TLS_KEY="$2"; shift 2 ;;
            --tls-cert)    [[ $# -ge 2 ]] || die "--tls-cert needs a file"; TLS_CERT="$2"; shift 2 ;;
            --from-release) SRC="release"; shift ;;
            --from-source) SRC="source"; shift ;;
            --yes|-y) YES=1; shift ;;
            --json)        JSON=1; shift ;;
            --dry-run)     DRY=1; shift ;;
            --purge)       PURGE=1; shift ;;
            --help|-h)     usage ;;
            help)          usage ;;
            update)        ACTION="update"; shift ;;
            uninstall)     ACTION="uninstall"; shift ;;
            status|start|stop|restart|logs|backup|auto-backup|tls|recovery|reset-password|reset-urlpath|menu)
                           die "'$1' moved to the manager — use: ovm $1" ;;
            install)       die "'install' is the default — just drop the word" ;;
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
        # /etc/os-release defines its own VERSION — keep the app version.
        local _app_version="$VERSION"
        # shellcheck disable=SC1091
        . /etc/os-release
        VERSION="$_app_version"
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
    if [[ -f "$file" ]]; then step "Backup  $file"; fi
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

# ── TLS ────────────────────────────────────────────────────────────────
# Private keys must never be world-readable. Native mode runs the panel as
# root (600 root-owned is fine); Docker mode runs it as appuser (uid 1000)
# with the files mounted read-only, so the key is owned by that uid. The
# certificate is public and stays 644.
secure_tls_files() {
    local key="$1" cert="$2"
    if [[ -f "$key" ]]; then
        chown 1000:1000 "$key" 2>/dev/null || true
        chmod 600 "$key"
    fi
    [[ -f "$cert" ]] && chmod 644 "$cert"
    return 0
}

generate_self_signed() {
    info "Self-signed certificate…"
    mkdir -p /etc/ssl/self-signed
    local cn; cn="$(hostname -I 2>/dev/null | awk '{print $1}')"
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout /etc/ssl/self-signed/privkey.pem \
        -out /etc/ssl/self-signed/fullchain.pem \
        -subj "/C=US/ST=Local/L=Local/O=OVManager/CN=${cn}" >/dev/null 2>&1
    secure_tls_files /etc/ssl/self-signed/privkey.pem /etc/ssl/self-signed/fullchain.pem
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
        --reloadcmd "chown 1000:1000 $outdir/privkey.pem 2>/dev/null || true; chmod 600 $outdir/privkey.pem; chmod 644 $outdir/fullchain.pem; systemctl restart $SYSTEMD_SERVICE >/dev/null 2>&1 || docker restart ovmanager >/dev/null 2>&1 || true" \
        >/dev/null 2>&1 || die "Failed to install certificate to $outdir"
    # Docker appuser (uid 1000) reads these via a read-only mount (renewals
    # re-apply perms through the reloadcmd above).
    secure_tls_files "$outdir/privkey.pem" "$outdir/fullchain.pem"
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
            secure_tls_files "$out/privkey.pem" "$out/fullchain.pem"
            TLS_KEY="$out/privkey.pem"; TLS_CERT="$out/fullchain.pem"
            ;;
        none) ;;
        *) die "Invalid TLS mode: '$TLS_MODE'" ;;
    esac
}

# ── Source / env ───────────────────────────────────────────────────────
release_base() { printf 'ovmanager-%s' "$VERSION"; }

release_url() {
    printf 'https://github.com/%s/releases/download/v%s/%s.tar.gz' \
        "$REPO" "$VERSION" "$(release_base)"
}

release_checksum_url() {
    printf 'https://github.com/%s/releases/download/v%s/%s.sha256' \
        "$REPO" "$VERSION" "$(release_base)"
}

# Download the versioned release file into $1 (an existing directory).
# The tarball holds a repo snapshot plus the prebuilt frontend/dist, so no
# git or npm is needed on the server. The .sha256 sidecar is verified when
# published; a missing sidecar only warns (older releases).
fetch_release() {
    local dest="$1" work base
    base="$(release_base)"
    work="$(mktemp -d)"
    run_step "Downloading release v${VERSION}" \
        curl -fsSLo "$work/$base.tar.gz" "$(release_url)" \
        || { rm -rf "$work"; die "No release file for v${VERSION} — try --from-source"; }
    if curl -fsSLo "$work/$base.sha256" "$(release_checksum_url)" 2>/dev/null; then
        ( cd "$work" && sha256sum -c "$base.sha256" >/dev/null ) \
            || { rm -rf "$work"; die "Release checksum mismatch for v${VERSION}"; }
        step "Checksum ok"
    else
        warn "No checksum file — skipping verification"
    fi
    mkdir -p "$dest"
    tar -xzf "$work/$base.tar.gz" -C "$dest" \
        || { rm -rf "$work"; die "Extract failed"; }
    rm -rf "$work"
    step "Release extracted"
}

fetch_source() {
    if [[ "$SRC" == "release" ]]; then
        fetch_release "$INSTALL_DIR"
        return
    fi
    if command -v git >/dev/null 2>&1; then
        run_step "Cloning ${REPO}@${BRANCH}" \
            git clone --depth 1 --branch "$BRANCH" "https://github.com/${REPO}.git" "$INSTALL_DIR"
    else
        local tmp
        tmp="$(mktemp)"
        run_step "Downloading source tarball" \
            curl -fsSLo "$tmp" "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
        mkdir -p "$INSTALL_DIR"
        tar -xzf "$tmp" --strip-components=1 -C "$INSTALL_DIR" \
            || { rm -f "$tmp"; die "Extract failed"; }
        rm -f "$tmp"
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
    # Subshell: the installer must keep its own working directory, or later
    # steps (node offer, registration) run from frontend/.
    (
        cd "$INSTALL_DIR/frontend" || exit 1
        run_step "Node.js dependencies" npm ci --no-audit --no-fund
        run_step "Frontend build" npm run build
    )
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
        [[ ${#ADMIN_PASS} -ge 12 ]] || die "Could not generate an admin password"
        warn "No password given — generated one (shown at the end)"
    fi
    validate_admin_password "$ADMIN_PASS"
    if [[ -n "$PATHPREFIX" ]]; then
        [[ "$PATHPREFIX" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "URL path: letters, digits, dash, underscore"
    fi
    if [[ "$WANT_NODE" -eq 1 ]]; then
        [[ -n "$NODE_NAME" ]] || NODE_NAME="ovnode"
        [[ "$NODE_NAME" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "Node name: 1–64 letters, digits, dash, underscore"
        [[ ${#NODE_KEY} -ge 16 ]] || die "Node API key must be at least 16 characters"
    fi
    case "$TLS_MODE" in
        le)
            [[ -n "$TLS_DOMAIN" ]] || die "--tls 2 needs --tls-domain DOMAIN" ;;
        le-ip|self|custom) ;;
        none)
            die "Plain HTTP is not allowed — pick TLS: 1 self-signed (default),\\n         2 Let's Encrypt domain, 3 Let's Encrypt IP, or 4 custom." ;;
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
        ADMIN_PASS="$(ask "Admin pass (blank = generate)" "" "h")"
        if [[ -n "$ADMIN_PASS" ]]; then
            prompt_validate_admin_password
        fi
    fi
    if [[ -z "$TLS_MODE" ]]; then
        line ""
        line "${B}TLS — encrypts your login and the panel (always on)${NC}"
        line "  ${WH}1${NC}  Self-signed (default)      encrypted; browser shows one warning to click through"        line "  ${WH}2${NC}  Let's Encrypt (domain)     needs a domain pointed here + free port 80"
        line "  ${WH}3${NC}  Let's Encrypt (this IP)    short-lived cert, no domain needed"
        line "  ${WH}4${NC}  Custom key + cert          you already have PEM files"
        local tls
        tls="$(ask "TLS" "1")"
        case "${tls:-1}" in
            1) TLS_MODE="self" ;;
            2) TLS_MODE="le"; TLS_DOMAIN="$(ask "Domain" "${TLS_DOMAIN:-}")"
               [[ -n "$TLS_DOMAIN" ]] || die "Domain required for Let's Encrypt" ;;
            3) TLS_MODE="le-ip"; TLS_DOMAIN="$(hostname -I 2>/dev/null | awk '{print $1}')" ;;
            4) TLS_MODE="custom"; TLS_KEY="$(ask "Key file" "")"; TLS_CERT="$(ask "Cert file" "")" ;;
            *) TLS_MODE="self" ;;
        esac
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

    hr; info "Downloading OVManager (v${VERSION}, ${SRC})"
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
        if [[ -d "$INSTALL_DIR/frontend/dist" ]]; then
            step "Frontend prebuilt"
        else
            build_frontend
        fi
        write_systemd_unit
        run_step "Service started" systemctl_bounded restart
    fi

    wait_health "${scheme}://127.0.0.1:${PORT}/health" 40 \
        || warn "No answer on /health yet — check logs"

    info "Finalizing first-boot…"
    if [[ "$MODE" == "docker" ]]; then
        docker restart ovmanager >/dev/null 2>&1 || true
    else
        systemctl_bounded restart >/dev/null 2>&1 || true
    fi
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 40 \
        || warn "No answer on /health after finalize"
    open_firewall_port "$PORT"
    install_cli
    success_card
    [[ "$JSON" -eq 1 ]] && emit_json 1
    offer_same_server_node
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
    if [[ "$SRC" == "release" ]]; then
        # .env is never in the tarball (uncommitted), so extracting over the
        # install keeps it. Stale files from older trees are harmless.
        fetch_release "$INSTALL_DIR"
    elif [[ -d .git ]]; then
        git stash --quiet 2>/dev/null || true
        run_step "Pull ${BRANCH}" git pull --rebase origin "$BRANCH"
        git stash pop --quiet 2>/dev/null || true
    else
        warn "No git checkout — re-downloading source (.env + data kept)"
        local tmp
        tmp="$(mktemp)"
        run_step "Downloading source" \
            curl -fsSLo "$tmp" "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
        tar -xzf "$tmp" --strip-components=1 -C "$INSTALL_DIR" || { rm -f "$tmp"; die "Extract failed"; }
        rm -f "$tmp"
    fi
    local scheme; scheme="$(scheme_of)"
    if [[ "$MODE" == "docker" ]]; then
        compose_up
    else
        run_step "Python packages" "$UV_BIN" sync --quiet
        if [[ -d "$INSTALL_DIR/frontend/dist" ]]; then
            step "Frontend prebuilt"
        else
            build_frontend
        fi
        run_step "Service restarted" systemctl_bounded restart
    fi
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 60 \
        || warn "No answer on /health — check logs"
    install_cli
    step "Update complete"
    line ""
    if [[ "$JSON" -eq 1 ]]; then emit_json 1; fi
    return 0
}


# Mirrors the panel's boot-time validation (backend/config.py): >= 12 chars
# and no placeholder-looking values.
# Empty output = acceptable; otherwise the human-readable reason.
admin_password_problem() {
    local pass="$1" lowered
    [[ -n "$pass" ]] || { printf 'must not be empty'; return 0; }
    [[ "$pass" != *$'\n'* && "$pass" != *$'\r'* ]] \
        || { printf 'must be a single line'; return 0; }
    [[ ${#pass} -ge 12 ]] \
        || { printf 'must be at least 12 characters (the panel requires >= 12)'; return 0; }
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
    die "No acceptable password after 3 tries (need >= 12 characters, not a common word)"
}

# Recovery for a lost owner password: rewrite only ADMIN_PASSWORD= in the
# installed .env, restart, then wait for /health. Never echoes the password.

do_uninstall() {
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    if [[ "$DRY" -eq 1 ]]; then
        info "Dry run — nothing changed (would stop the service and remove $INSTALL_DIR)."
        exit 0
    fi
    confirm "Remove OVManager and stop the service?" || die "Cancelled."
    systemctl_bounded stop
    systemctl disable "$SYSTEMD_SERVICE" 2>/dev/null || true
    rm -f "/etc/systemd/system/$SYSTEMD_SERVICE"
    systemctl daemon-reload 2>/dev/null || true
    if command -v docker >/dev/null 2>&1 && [[ -f "$COMPOSE_FILE" ]]; then
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" down ) >/dev/null 2>&1 || true
        docker rm -f ovmanager >/dev/null 2>&1 || true
    fi
    remove_cli
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
    if ! can_prompt; then
        fail "Already installed. Re-run with:  $0 update"
        exit 2
    fi
    info "Manage the panel with: ovm  (status, logs, backup, TLS, recovery)"
    while true; do
        local tag
        tag="$(tui_select "OVManager — installer" \
            update    "Update to the latest release" \
            uninstall "Uninstall" \
            quit      "Quit")"
        case "$tag" in
            update)    check_root; detect_os; check_deps; do_update || warn "Update failed" ;;
            uninstall)
                check_root
                confirm_no "Also delete data and backups?" && PURGE=1
                do_uninstall
                return 0 ;;
            *)         return 0 ;;
        esac
    done
}


# ── Start menu / Express / same-server node ────────────────────────────

# Express preset: safe defaults, then the single admin-password question.
panel_express_defaults() {
    EXPRESS=1
    : "${MODE:=native}"
    : "${PORT:=$DEFAULT_PORT}"
    if [[ "$PATH_SET" -eq 0 ]]; then PATHPREFIX="$(rand_path)"; fi
    : "${ADMIN_USER:=$DEFAULT_USER}"
    [[ -n "$TLS_MODE" ]] || TLS_MODE="self"
    if [[ -z "$ADMIN_PASS" ]]; then
        line ""
        ADMIN_PASS="$(ask "Admin password (blank = generate)" "" "h")"
        if [[ -z "$ADMIN_PASS" ]]; then
            GENERATED_PASS=1
        else
            prompt_validate_admin_password
        fi
    fi
    # Explicit success: a trailing `[[ ... ]] && ...` returning non-zero would
    # trip `set -e` and exit the whole installer right after the prompt.
    return 0
}

# Friendly front door, shown only for a bare interactive invocation.
start_menu() {
    line "  What do you want to do?"
    line ""
    line "  ${GR}1${NC})  Express    Install with safe defaults (recommended)"
    line "  ${WH}2${NC})  Custom     Choose every option yourself"
    line ""
    local choice
    choice="$(ask "Select" "1")"
    case "${choice:-1}" in
        1) panel_express_defaults ;;
        2) EXPRESS=0 ;;
        *) panel_express_defaults ;;
    esac
    line ""
}

# After the Ready card: offer a same-server node (interactive installs only).
# Express registers it in the panel automatically; Custom asks first.
offer_same_server_node() {
    [[ "$DRY" -eq 0 && "$JSON" -eq 0 ]] || return 0
    can_prompt || return 0
    line ""
    # Default NO: a bare Enter must not provision a VPN node.
    if ! confirm_no "Install a VPN node on this same server too?"; then
        info "Skipped. Install OVNode on a separate server and add it in"
        info "Nodes → Add Node — or re-run this installer with --with-node."
        return 0
    fi
    warn "Not recommended for production: a node on its own server keeps"
    warn "panel and VPN traffic independent. Continuing anyway."
    local node_name node_key node_port=2083
    node_name="$(ask "Node name" "ovnode")"
    [[ "$node_name" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "Node name: 1–64 letters, digits, dash, underscore"
    node_key="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    while port_in_use "$node_port"; do node_port=$((node_port + 1)); done

    local node_repo="${OVNODE_REPO:-anonysec/OVNode}" node_branch="${OVNODE_BRANCH:-main}"
    local url="https://raw.githubusercontent.com/${node_repo}/${node_branch}/install.sh"
    local tmp; tmp="$(mktemp)"
    local node_tls="1"
    info "Installing OVNode '${node_name}' (Express)…"
    local node_json="" rc=0
    if curl -fsSL "$url" -o "$tmp" 2>/dev/null; then
        node_json="$(bash "$tmp" install --json --name "$node_name" --api-key "$node_key" \
                        --tls selfsigned --port "$node_port")" || rc=$?
    else
        rc=1
    fi
    rm -f "$tmp"
    if [[ "$rc" -eq 0 ]]; then
        step "VPN node installed (service port ${node_port}, TLS self-signed)"
    elif [[ "$rc" -eq 3 && -f /opt/ovnode/.env ]]; then
        # The node agent is already installed here: adopt its settings instead
        # of failing, then register that node in the panel.
        warn "OVNode is already installed on this server — registering the existing node."
        node_name="$(env_get /opt/ovnode/.env NODE_NAME)"; : "${node_name:=ovnode}"
        node_key="$(env_get /opt/ovnode/.env API_KEY)"
        node_port="$(env_get /opt/ovnode/.env SERVICE_PORT)"; : "${node_port:=2083}"
        [[ "$(env_get /opt/ovnode/.env TLS_METHOD)" == "none" ]] && node_tls="0"
        if [[ -z "$node_key" ]]; then
            warn "Could not read the node API key from /opt/ovnode/.env — add the node manually."
            return 0
        fi
    else
        warn "Node install failed (exit $rc) — install OVNode later, then add it via Nodes → Add Node."
        return 0
    fi

    local auto=1
    if [[ "$EXPRESS" -eq 0 ]]; then
        confirm "Add it to the panel automatically now?" || auto=0
    fi
    if [[ "$auto" -eq 1 ]] && register_node_in_panel "$node_name" "$node_key" "$node_port" "$node_tls"; then
        return 0
    fi
    print_node_registration "$node_name" "$node_key" "$node_port"
}

# Log into the fresh panel (loopback) and POST the node. Best-effort: any
# failure falls back to printing the details for manual entry.
register_node_in_panel() {
    local name="$1" key="$2" port="$3" use_tls="${4:-1}"
    local base scheme ip token payload resp
    scheme="$(scheme_of)"
    base="${scheme}://127.0.0.1:${PORT}"
    [[ -n "$PATHPREFIX" ]] && base="${base}/${PATHPREFIX}"
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [[ -n "$ip" ]] || { warn "Could not detect this server's IP."; return 1; }

    token="$(curl -sk --max-time 20 -X POST "${base}/api/login" \
        -H "X-Requested-With: XMLHttpRequest" \
        --data-urlencode "username=${ADMIN_USER}" \
        --data-urlencode "password=${ADMIN_PASS}" 2>/dev/null \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null)" || true
    if [[ -z "$token" ]]; then
        warn "Could not log in to the panel automatically."
        return 1
    fi

    payload="$(python3 - "$name" "$ip" "$port" "$key" "$use_tls" <<'PY'
import json, sys
name, ip, port, key = sys.argv[1:5]
print(json.dumps({
    "name": name,
    "address": ip,
    "tunnel_address": ip,
    "protocol": "udp",
    "ovpn_port": 1194,
    "port": int(port),
    "key": key,
    "status": True,
    "set_new_setting": True,
    "use_tls": bool(int(sys.argv[5])),
}))
PY
)"
    resp="$(curl -sk --max-time 30 -X POST "${base}/api/nodes/" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        -H "X-Requested-With: XMLHttpRequest" \
        -d "$payload" 2>/dev/null)" || true
    # Tolerant parse: take the FIRST JSON object. Some proxies/appended bodies
    # made a strict json.load() fail with "Extra data" even when the node was
    # added, which turned a success into a scary warning.
    if python3 -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit(1)
obj, _ = json.JSONDecoder().raw_decode(raw)
raise SystemExit(0 if obj.get("success") else 1)
' <<<"${resp:-}"; then
        step "Node '${name}' added to the panel."
        return 0
    fi

    # The response may be a duplicate/truncated body; ask the panel directly.
    local check
    check="$(curl -sk --max-time 20 -H "Authorization: Bearer ${token}" "${base}/api/nodes/" 2>/dev/null)" || true
    if python3 -c '
import json, sys
name = sys.argv[1]
raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit(1)
obj, _ = json.JSONDecoder().raw_decode(raw)
nodes = (obj.get("data") if isinstance(obj, dict) else obj) or []
raise SystemExit(0 if any((n or {}).get("name") == name for n in nodes) else 1)
' "$name" <<<"${check:-}"; then
        step "Node '${name}' is registered in the panel."
        return 0
    fi

    warn "Panel did not accept the node (${#resp} bytes): $(printf '%s' "$resp" | head -c 200)"
    return 1
}

print_node_registration() {
    local name="$1" key="$2" port="$3"
    local ip; ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    line ""
    info "Add the node manually in the panel: Nodes → Add Node"
    kv "Name"    "$name"
    kv "Address" "${ip:-<this server IP>}"
    kv "Port"    "$port"
    kv "TLS"     "on (self-signed)"
    kv "API key" "$key"
    line ""
}

# ── Terminal command (TUI) ─────────────────────────────────────────────
# The installer copies itself to $BIN_DIR as "ovmanager" (+ "ovm" alias), so
# a bare `ovmanager` opens this menu. Every action is also a plain subcommand
# for scripts: status | start | stop | restart | logs [N|-f] | backup |
# update | tls | recovery | reset-password | reset-urlpath | uninstall.

is_docker_mode() { [[ -f "$COMPOSE_FILE" ]]; }

env_get() {  # env_get FILE KEY → value (empty when missing)
    [[ -f "$1" ]] || return 0
    awk -F= -v k="$2" '$1 == k { sub(/^[^=]*=/, ""); print; exit }' "$1" | tr -d '\r'
}

env_set() {  # env_set FILE KEY VALUE — rewrite one line, atomically
    local file="$1" key="$2" value="$3" tmp
    if [[ ! -f "$file" ]]; then
        printf '%s=%s\n' "$key" "$value" >> "$file"
        return 0
    fi
    tmp="$(mktemp "${file}.XXXXXX")" || die "Could not create a temp file next to $file"
    ENV_K="$key" ENV_V="$value" awk '
        BEGIN { k = ENVIRON["ENV_K"]; v = ENVIRON["ENV_V"]; done = 0 }
        index($0, k "=") == 1 { if (!done) { print k "=" v; done = 1 } ; next }
        { print }
        END { if (!done) print k "=" v }
    ' "$file" > "$tmp" || { rm -f "$tmp"; die "Could not update $file"; }
    chmod --reference="$file" "$tmp" 2>/dev/null || chmod 600 "$tmp"
    chown --reference="$file" "$tmp" 2>/dev/null || true
    mv -f "$tmp" "$file"
}

# systemd waits up to TimeoutStopSec (90s default) for a stuck service, which
# operators read as a frozen installer. Bound the wait, then force the unit.
STOP_TIMEOUT="${OVM_STOP_TIMEOUT:-20}"

systemctl_bounded() {  # systemctl_bounded stop|restart [unit]
    local action="$1" unit="${2:-$SYSTEMD_SERVICE}"
    # Not loaded (fresh machine, Docker install): nothing to stop, no warning.
    if [[ "$(systemctl show -p LoadState --value "$unit" 2>/dev/null)" != "loaded" ]]; then
        return 0
    fi
    if timeout "$STOP_TIMEOUT" systemctl "$action" "$unit" 2>/dev/null; then
        return 0
    fi
    warn "systemctl $action $unit did not finish in ${STOP_TIMEOUT}s — forcing it"
    systemctl kill -s SIGKILL "$unit" >/dev/null 2>&1 || true
    sleep 1
    if [[ "$action" == "restart" ]]; then
        timeout "$STOP_TIMEOUT" systemctl start "$unit" 2>/dev/null || true
    fi
    return 0
}




# Keep only the newest N tarballs this installer writes (/var/backups).


# Host-level daily backup: a systemd timer that runs `ovmanager backup`.
# Separate from the panel-scheduled backup (Settings → Advanced → Backup).








# Boxed menu when whiptail is already installed; colored menu otherwise.
tui_select() {  # tui_select "Title" tag label [tag label ...] → prints the tag
    local title="$1"; shift
    local tags=() labels=() tag label i=0
    while [[ $# -ge 2 ]]; do tags+=("$1"); labels+=("$2"); shift 2; done
    if command -v whiptail >/dev/null 2>&1 && can_prompt; then
        local args=() out
        for tag in "${tags[@]}"; do args+=("$tag" "${labels[$i]}"); i=$((i + 1)); done
        out="$(whiptail --title "$title" --menu "Choose an action" 24 78 12 "${args[@]}" 3>&1 1>&2 2>&3)" && {
            printf '%s' "$out"
            return 0
        }
        return 0
    fi
    line "${B}${title}${NC}"; line ""
    i=0
    for tag in "${tags[@]}"; do
        i=$((i + 1))
        printf '  %b%d%b)  %s\n' "$WH" "$i" "$NC" "${labels[$((i - 1))]}" >&2
    done
    line ""
    local choice; choice="$(ask "Select" "1")"
    [[ "$choice" =~ ^[0-9]+$ ]] || { printf '%s' "${tags[0]}"; return 0; }
    printf '%s' "${tags[$(((choice - 1) % ${#tags[@]}))]}"
}

install_cli() {
    # The manager is the day-to-day command (ovmanager/ovm). Refreshed on
    # every update, which auto-swaps boxes whose ovm is an old installer copy.
    local src="${INSTALL_DIR}/manager.sh"
    [[ -f "$src" ]] || return 0
    mkdir -p "$BIN_DIR" 2>/dev/null || { warn "Could not create $BIN_DIR"; return 0; }
    if cp -f "$src" "$BIN_DIR/$CLI_NAME" 2>/dev/null && chmod 0755 "$BIN_DIR/$CLI_NAME"; then
        ln -sf "$CLI_NAME" "$BIN_DIR/$CLI_ALIAS" 2>/dev/null || true
        step "Command  ${BIN_DIR}/${CLI_NAME}  (alias: ${CLI_ALIAS})"
    else
        warn "Could not install the $CLI_NAME command into $BIN_DIR"
    fi
}

remove_cli() {
    rm -f "$BIN_DIR/$CLI_NAME" "$BIN_DIR/$CLI_ALIAS" 2>/dev/null || true
}

# ── Main ───────────────────────────────────────────────────────────────
main() {
    parse_args "$@"
    apply_env
    case "$SRC" in
        release|source) ;;
        *) die "Invalid source '$SRC' (use release or source)" ;;
    esac
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
        update)
            detect_os
            if [[ "$DRY" -eq 1 ]]; then
                info "Dry run — nothing changed (would back up data, fetch ${SRC}, rebuild if needed)."
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

    # Bare interactive run → friendly start menu (Express/Custom/Update/Uninstall).
    if [[ "$CLI_GIVEN" -eq 0 && "$DRY" -eq 0 && "$JSON" -eq 0 ]] && can_prompt; then
        start_menu
    fi

    if can_prompt && [[ "$YES" -eq 0 ]]; then
        if [[ "$EXPRESS" -eq 1 ]]; then
            # Express already collected its single answer (admin password).
            :
        else
            wizard
        fi
    else
        : "${PORT:=$DEFAULT_PORT}"
        if [[ "$PATH_SET" -eq 0 ]]; then
            PATHPREFIX="$(rand_path)"
        fi
        : "${ADMIN_USER:=$DEFAULT_USER}"
        : "${TLS_MODE:=self}"
        : "${MODE:=native}"
        if [[ "$WANT_NODE" -eq 1 ]]; then
            : "${NODE_NAME:=ovnode}"
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
        die "Port 80 is busy — Let's Encrypt standalone needs it (or --tls 1 for now)"
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
