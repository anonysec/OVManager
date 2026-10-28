#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# OVManager installer — bootstraps the Go binary.
#
# Zero-question by default:
#   bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
#
# Interactive mode (prompts for port, URL path, and optional Let's Encrypt domain):
#   bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) -i
#
# Environment overrides (CI/CD):
#   OVM_PORT=8443 OVM_URLPATH=panel bash <(curl -fsSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
#
# Automatic Let's Encrypt TLS at bootstrap:
#   bash <(curl -fsSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) --acme star.example.com
#
# Uninstall:
#   bash <(curl -fsSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) uninstall
#   bash <(curl -fsSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) uninstall --purge
#
# Dev install from a working tree (rsync + go build + a dev unit):
#   ./install.sh --build [DIR] [--dest DIR]
#
set -Eeuo pipefail

# ── Configuration ──────────────────────────────────────────────────────
REPO="${OVM_REPO:-anonysec/OVManager}"
APP_SLUG="ovmanager"
INSTALL_DIR="${OVM_INSTALL_DIR:-/opt/ovmanager}"
DATA_DIR="${OVM_DATA_DIR:-/var/lib/ovmanager}"
DEFAULT_PORT="${OVM_DEFAULT_PORT:-2095}"
DEFAULT_URLPATH="${OVM_DEFAULT_URLPATH:-dashboard}"
DEFAULT_USER="admin"
SYSTEMD_SERVICE="ovmanager.service"
VERSION="${OVM_VERSION:-2.1.3}"
IMAGE_REPO="${OVM_IMAGE_REPO:-ghcr.io/anonysec/ovmanager}"
if [[ -f internal/version/version.go ]]; then
    VERSION=$(grep -E '^const Version = ' internal/version/version.go | sed -E 's/.*"([^"]+)".*/\1/')
fi
BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"
PANEL_USER="${OVM_PANEL_USER:-ovmanager}"
CLI_NAME="ovmanager"

# ── Defaults ───────────────────────────────────────────────────────────
PORT_VAL="${OVM_PORT:-$DEFAULT_PORT}"
URLPATH_VAL="${OVM_URLPATH:-$DEFAULT_URLPATH}"
HEALTH_TIMEOUT="${OVM_HEALTH_TIMEOUT:-40}"
ACME_TIMEOUT="${OVM_ACME_TIMEOUT:-60}"
INTERACTIVE=0
YES=0
FROM_SOURCE=0
DOCKER=0
SRC=""
DEST=""
ACTION="install"
UPDATE_ARGS=()

# ── Output helpers ─────────────────────────────────────────────────────
if [[ -t 2 ]]; then
    _GREEN='\033[32m'
    _YELLOW='\033[33m'
    _BLUE='\033[34m'
    _RED='\033[31m'
    _RESET='\033[0m'
else
    _GREEN=''
    _YELLOW=''
    _BLUE=''
    _RED=''
    _RESET=''
fi

_ok()    { printf "  ${_GREEN}✓${_RESET}  %s\n" "$*" >&2; }
_note()  { printf "  ${_BLUE}…${_RESET}  %s\n" "$*" >&2; }
_warn()  { printf "  ${_YELLOW}⚠${_RESET}  %s\n" "$*" >&2; }
_stage() { printf '\n  ============================== %s ==============================\n' "$*" >&2; }
die()    { printf "install: ${_RED}error${_RESET}: %s\n" "$*" >&2; exit 1; }

# ── Dependency checks ──────────────────────────────────────────────────
has_systemd() { command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; }
check_root()  { [[ "$EUID" -eq 0 ]] || die "Must run as root (sudo)."; }

check_deps() {
    local missing=()
    for cmd in curl install sha256sum openssl; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    [[ ${#missing[@]} -eq 0 ]] \
        || die "Missing required tools: ${missing[*]}"
}

# ── Port conflict check ────────────────────────────────────────────────
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

# ── Architecture detection ──────────────────────────────────────────────
detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64)   printf 'amd64' ;;
        aarch64|arm64)  printf 'arm64' ;;
        *)              die "Unsupported architecture: $(uname -m) (need x86_64 or aarch64)" ;;
    esac
}

release_asset() { printf '%s-linux-%s' "$APP_SLUG" "$(detect_arch)"; }

release_url() {
    printf 'https://github.com/%s/releases/download/v%s/%s' \
        "$REPO" "$VERSION" "$(release_asset)"
}

release_checksum_url() { printf '%s.sha256' "$(release_url)"; }

# ── Release fetch with retry ────────────────────────────────────────────
fetch_release() {
    local dest="$1" work asset
    asset="$(release_asset)"
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT

    _note "fetching v$VERSION ($asset)"

    # Retry up to 3 times with exponential backoff
    local retries=0
    while true; do
        if curl -fsSL --max-time 60 --retry 3 --retry-delay 2 --retry-max-time 120 \
            -o "$work/$asset" "$(release_url)" 2>/dev/null; then
            break
        fi
        retries=$((retries + 1))
        if [[ $retries -ge 3 ]]; then
            rm -rf "$work"
            die "No release file for v$VERSION — see https://github.com/$REPO/releases"
        fi
        sleep $((2 ** retries))
    done

    if ! curl -fsSL --max-time 30 --retry 2 \
        -o "$work/$asset.sha256" "$(release_checksum_url)" 2>/dev/null; then
        rm -rf "$work"
        die "Release checksum file is missing for v$VERSION"
    fi

    if ! ( cd "$work" && sha256sum -c "$asset.sha256" >/dev/null 2>&1 ); then
        rm -rf "$work"
        die "Release checksum mismatch for v$VERSION — possible tampering or incomplete download"
    fi

    mkdir -p "$dest"
    install -m 0755 "$work/$asset" "$dest/$APP_SLUG"
    chown root:root "$dest/$APP_SLUG"
    rm -rf "$work"
    trap - EXIT
    _ok "installed v$VERSION to $dest"
}

# ── Environment helpers ─────────────────────────────────────────────────
read_env_value() {
    local envfile="$1" key="$2" val
    val="$(awk -F= -v k="$key" '$1==k {print $2; exit}' "$envfile" 2>/dev/null)"
    printf '%s' "${val:-}"
}

# ── Interactive prompt ───────────────────────────────────────────────────
validate_port() {
    local p="$1"
    [[ "$p" =~ ^[0-9]+$ ]] && [[ "$p" -ge 1 && "$p" -le 65535 ]]
}

validate_urlpath() {
    local p="$1"
    # Must not be empty, reserved, or contain special chars
    [[ -n "$p" ]] || return 0
    [[ "$p" != "api" && "$p" != "assets" && "$p" != "health" && \
       "$p" != "static" && "$p" != "doc" && "$p" != "openapi.json" ]] || return 1
    [[ "$p" =~ ^[A-Za-z0-9_-]+$ ]]
}

check_acme_domain() {
    [[ -z "${OVM_ACME_DOMAIN:-}" ]] && return 0
    # If a valid certificate already exists, do not re-issue.
    if [[ -s "$DATA_DIR/tls/fullchain.pem" && -s "$DATA_DIR/tls/privkey.pem" ]]; then
        if check="$(openssl x509 -in "$DATA_DIR/tls/fullchain.pem" -noout -checkend 86400 2>/dev/null)" && [[ "$check" == "Certificate will not expire"* ]]; then
            _ok "acme    existing certificate still valid - skipping issuance"
            OVM_ACME_DOMAIN=""
            return 0
        fi
    fi
    # Let'''s Encrypt HTTP-01 needs port 80 free. If something (nginx/apache)
    # already holds it, skip auto-issuance and let the operator run
    # `ovmanager tls` later, optionally behind a reverse proxy.
    if (exec 3<>/dev/tcp/127.0.0.1/80) 2>/dev/null; then
        exec 3>&- 3<&- 2>/dev/null || true
        _warn "port 80 is in use - skipping auto ACME issuance"
        _note "free port 80 or proxy /.well-known/acme-challenge/ to the panel, then run: ovmanager tls issue $OVM_ACME_DOMAIN"
        OVM_ACME_DOMAIN=""
        return 0
    fi
    local d="$OVM_ACME_DOMAIN"
    # Basic DNS name validation
    if [[ "$d" != *[!A-Za-z0-9.-]* && "$d" == *.* && \
          "$d" != -* && "$d" != *. && "$d" != *..* && "$d" != *-. && "$d" != -*. ]]; then
        _ok "acme    Let's Encrypt issuance scheduled for $OVM_ACME_DOMAIN"
        return 0
    fi
    _warn "OVM_ACME_DOMAIN '$OVM_ACME_DOMAIN' is not a valid DNS name — issuing is skipped, the panel stays on plain HTTP"
    OVM_ACME_DOMAIN=""
}

prompt_interactive() {
    [[ "$INTERACTIVE" -eq 1 && "$YES" -eq 0 ]] || return 0
    [[ -t 0 ]] || return 0

    printf '\n  ╔══════════════════════════════════════════════╗\n' >&2
    printf '  ║  OVManager installer  v%-24s║\n' "$VERSION" >&2
    printf '  ╚══════════════════════════════════════════════╝\n' >&2
    local in_port in_path in_acme

    read -r -p "  Panel Port [${PORT_VAL}]: " in_port </dev/tty || true
    if [[ -n "${in_port// /}" ]]; then
        in_port="${in_port// /}"
        if validate_port "$in_port"; then
            PORT_VAL="$in_port"
        else
            _warn "Invalid port '$in_port', using default $PORT_VAL"
        fi
    fi

    read -r -p "  URL Path [${URLPATH_VAL}]: " in_path </dev/tty || true
    in_path="${in_path// /}"
    in_path="${in_path#/}"
    in_path="${in_path%/}"
    if [[ -n "$in_path" ]]; then
        if validate_urlpath "$in_path"; then
            URLPATH_VAL="$in_path"
        else
            _warn "Invalid URL path '$in_path', using default $URLPATH_VAL"
        fi
    fi

    if [[ -z "${OVM_ACME_DOMAIN:-}" ]]; then
        read -r -p "  Panel domain or IP (optional, e.g. panel.example.com or 203.0.113.1): " in_acme </dev/tty || true
        in_acme="${in_acme// /}"
        if [[ -n "$in_acme" ]]; then
            OVM_ACME_DOMAIN="$in_acme"
        fi
    fi
    printf '  ────────────────────────────────────────────────\n' >&2
}

# ── Environment file ────────────────────────────────────────────────────
write_env() {
    local envfile="$1" data_dir="$2" dest="${3:-$INSTALL_DIR}"
    if [[ -f "$envfile" ]]; then
        chmod 600 "$envfile" 2>/dev/null || true
        return 0
    fi

    mkdir -p "$data_dir"

    (
    umask 077
    {
        printf 'HOST=127.0.0.1\n'
        printf 'PORT=%s\n' "$PORT_VAL"
        printf 'URLPATH=%s\n' "$URLPATH_VAL"
        printf 'ADMIN_USERNAME=%s\n' "$DEFAULT_USER"
        printf 'DATA_DIR=%s\n' "$data_dir"
        if [[ -n "${OVM_ACME_DOMAIN:-}" ]]; then
            printf 'SSL_CERTFILE=%s/tls/fullchain.pem\n' "$data_dir"
            printf 'SSL_KEYFILE=%s/tls/privkey.pem\n' "$data_dir"
            printf 'OVM_ACME_DOMAIN=%s\n' "$OVM_ACME_DOMAIN"
            mkdir -p "$data_dir/tls"
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

# ── Claim key ──────────────────────────────────────────────────────────
mint_claim_key() {
    local path="$1" key
    mkdir -p "$(dirname "$path")"
    if [[ -f "$path" ]]; then
        return 0
    fi
    key="$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-32)"
    ( umask 077; printf '%s\n' "$key" > "$path" )
    chmod 600 "$path"
    chown "$PANEL_USER:$PANEL_USER" "$path"
    printf '%s\n' "$key"
}

# ── Panel user ─────────────────────────────────────────────────────────
ensure_panel_user() {
    mkdir -p "$DATA_DIR"
    if ! id -u "$PANEL_USER" >/dev/null 2>&1; then
        useradd --system --no-create-home --home-dir "$DATA_DIR" \
            --shell /usr/sbin/nologin \
            --comment "OVManager panel service account" "$PANEL_USER" >/dev/null 2>&1 \
            || die "Could not create the $PANEL_USER account"
    fi
    if getent group systemd-journal >/dev/null 2>&1; then
        usermod -a -G systemd-journal "$PANEL_USER" 2>/dev/null || true
    fi
}

# ── Unit hardening ──────────────────────────────────────────────────────
unit_hardening() {
    local p
    for p in "$@"; do
        case "$p/" in
            /tmp/*|/var/tmp/*|/run/*|/home/*|/root/*|/dev/shm/*) return 0 ;;
        esac
    done
    printf 'NoNewPrivileges=yes\nPrivateTmp=yes\nProtectHome=yes\n'
}

# ── Systemd units ───────────────────────────────────────────────────────
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
ExecStart=$dest/$APP_SLUG
Restart=on-failure
RestartSec=3
AmbientCapabilities=CAP_NET_BIND_SERVICE
$(unit_hardening "$dest" "$DATA_DIR")
# ProtectSystem is deliberately NOT set. The panel writes the operator-
# declared certificate and key (SSL_CERTFILE / SSL_KEYFILE), which on a
# standard Let's Encrypt install live under /etc/letsencrypt — outside
# DATA_DIR. systemd 259's ProtectSystem=full also mounts /etc read-only, and
# =strict mounts the whole hierarchy read-only, so either one would break
# certificate upload, ACME issuance and certificate rollback. NoNewPrivileges
# and PrivateTmp harden the unit without fighting that contract.

[Install]
WantedBy=multi-user.target
UNIT
    chmod 644 "/etc/systemd/system/$SYSTEMD_SERVICE"
}

write_backup_units() {
    local dest="${1:-$INSTALL_DIR}"
    cat > "/etc/systemd/system/${SYSTEMD_SERVICE%.service}-backup.service" <<UNIT
[Unit]
Description=OVManager daily backup
After=${SYSTEMD_SERVICE}

[Service]
Type=oneshot
EnvironmentFile=$dest/.env
User=$PANEL_USER
Group=$PANEL_USER
ExecStart=$dest/$APP_SLUG backup --keep 7
UNIT

    cat > "/etc/systemd/system/${SYSTEMD_SERVICE%.service}-backup.timer" <<UNIT
[Unit]
Description=Run the OVManager daily backup

[Timer]
OnCalendar=*-*-* 01:15:00
RandomizedDelaySec=45min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    chmod 644 /etc/systemd/system/${SYSTEMD_SERVICE%.service}-backup.service \
              /etc/systemd/system/${SYSTEMD_SERVICE%.service}-backup.timer
}

write_acme_renew_units() {
    cat > "/etc/systemd/system/${SYSTEMD_SERVICE%.service}-acme-renew.service" <<UNIT
[Unit]
Description=OVManager ACME certificate renewal check
After=${SYSTEMD_SERVICE}

[Service]
Type=oneshot
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/$APP_SLUG tls renew
UNIT

    cat > "/etc/systemd/system/${SYSTEMD_SERVICE%.service}-acme-renew.timer" <<UNIT
[Unit]
Description=Run the OVManager ACME renewal check weekly

[Timer]
OnCalendar=weekly
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    chmod 644 /etc/systemd/system/${SYSTEMD_SERVICE%.service}-acme-renew.service \
              /etc/systemd/system/${SYSTEMD_SERVICE%.service}-acme-renew.timer
}

enable_acme_renew_timer() {
    systemctl daemon-reload
    systemctl enable --now "${SYSTEMD_SERVICE%.service}-acme-renew.timer" >/dev/null 2>&1 \
        || _warn "Could not enable the ACME renew timer"
}

enable_backup_timer() {
    systemctl daemon-reload
    systemctl enable --now "${SYSTEMD_SERVICE%.service}-backup.timer" >/dev/null 2>&1 \
        || _warn "Could not enable the backup timer (enable it with: systemctl enable --now ${SYSTEMD_SERVICE%.service}-backup.timer)"
}

# The panel user must be able to read the code and the config, and to write its
# data dir — and nothing else. The .env stays root-owned and group-readable so
# the config never lands in a file the panel user owns (and could rewrite).
grant_panel_access() {
    local dest="${1:-$INSTALL_DIR}"
    chmod 755 "$dest"
    chmod 755 "$dest/$APP_SLUG"
    mkdir -p "$DATA_DIR"
    chown -R "$PANEL_USER:$PANEL_USER" "$DATA_DIR"
    chmod 700 "$DATA_DIR"
    chown "root:$PANEL_USER" "$dest/.env"
    chmod 640 "$dest/.env"
}

install_cli() {
    local dest="${1:-$INSTALL_DIR}"
    mkdir -p "$BIN_DIR" 2>/dev/null || { _warn "Could not create $BIN_DIR"; return 0; }
    if [[ -L "$BIN_DIR/$CLI_NAME" ]]; then
        local existing
        existing="$(readlink -f "$BIN_DIR/$CLI_NAME" 2>/dev/null || true)"
        if [[ "$existing" != "$dest/$APP_SLUG" ]]; then
            _warn "CLI link already points to $existing — replacing with $dest/$APP_SLUG"
        fi
    fi
    ln -sf "$dest/$APP_SLUG" "$BIN_DIR/$CLI_NAME"
    _ok "command  $BIN_DIR/$CLI_NAME"
}

# ── ACME verification ──────────────────────────────────────────────────
verify_acme() {
    local data_dir="$1" cert key i check
    cert="$data_dir/tls/fullchain.pem"
    key="$data_dir/tls/privkey.pem"
    _note "waiting for the Let's Encrypt certificate (up to $((ACME_TIMEOUT * 3))s)…"
    for ((i = 0; i < ACME_TIMEOUT; i++)); do
        if [[ -s "$cert" && -s "$key" ]]; then
            if check="$(openssl x509 -in "$cert" -noout -checkend 86400 2>/dev/null)" && [[ "$check" == "Certificate will not expire"* ]]; then
                _ok "acme    certificate installed at $cert"
                _note "point your front TLS proxy (or a TLS vhost) at these files to go live"
                return 0
            fi
        fi
        sleep 3
    done
    _warn "no Let's Encrypt certificate after 3 minutes — the panel continues on plain HTTP"
    _warn "  check journalctl -u $SYSTEMD_SERVICE, or issue from Settings → HTTPS in the panel"
    return 0
}

# ── Health check ────────────────────────────────────────────────────────
verify_health() {
    local port="$1" want="$2" i body got
    local host="127.0.0.1"
    for ((i = 0; i < HEALTH_TIMEOUT; i++)); do
        body="$(curl -fsS --max-time 3 "http://${host}:${port}/health" 2>/dev/null || true)"
        if [[ -n "$body" ]]; then
            got="$(printf '%s' "$body" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)"
            if [[ "$got" == "$want" ]]; then
                _ok "health  v$got on port $port"
                return 0
            fi
            [[ -n "$got" ]] && _warn "health reports '$got', expected '$want'"
        fi
        printf '.' >&2
        sleep 1
    done
    printf '\n' >&2
    return 1
}

# ── Dev install from source ─────────────────────────────────────────────
do_from_source() {
    local src="${SRC:-$PWD}" dest="${DEST:-$INSTALL_DIR}"
    local service unit port key health

    [[ -d "$src" ]] || die "no source directory: $src"
    [[ -f "$src/cmd/main.go" ]] || die "no Go source tree in $src (cmd/main.go missing)"
    [[ -d "$src/web/dist" ]] || die "web/dist missing in $src — run: cd web && npm run build"

    check_root
    ensure_panel_user
    [[ -n "$dest" && "$dest" != "/" ]] || die "refusing to operate on '$dest'"
    command -v rsync >/dev/null || die "rsync not found"
    command -v go >/dev/null || die "go not found — install Go 1.27+ (https://go.dev/dl/)"

    dest="${dest%/}"
    if [[ "$dest" == "$INSTALL_DIR" ]]; then
        if [[ -e "$INSTALL_DIR/$APP_SLUG" || -e "/etc/systemd/system/$SYSTEMD_SERVICE" ]]; then
            die "--build refuses to overwrite the live install at $INSTALL_DIR; pass --dest DIR for a test install"
        fi
    fi
    service="$(basename "$dest").service"
    unit="/etc/systemd/system/$service"

    rsync -a --delete \
        --exclude .git \
        --exclude .venv \
        --exclude __pycache__ \
        --exclude node_modules \
        --exclude .pytest_cache \
        --exclude .slim \
        --exclude .env \
        --exclude /data \
        "$src/" "$dest/"

    mkdir -p "$dest/internal/webfs/dist"
    cp -a "$dest/web/dist/." "$dest/internal/webfs/dist/"
    ( cd "$dest" && go build -o "$APP_SLUG" ./cmd )

    mkdir -p "$dest/data"
    chown -R "$PANEL_USER:$PANEL_USER" "$dest/data"
    chmod 700 "$dest/data"

    if [[ ! -f "$dest/.env" ]]; then
        cat > "$dest/.env" <<EOF
# Generated by install.sh --build. Kept across reruns, never overwritten.
PORT=2095
URLPATH=dashboard
HOST=127.0.0.1
DATA_DIR=$dest/data
ADMIN_USERNAME=admin
EOF
        chown "root:$PANEL_USER" "$dest/.env"
        chmod 640 "$dest/.env"
    fi

    if [[ ! -f "$dest/data/owner-claim.key" ]]; then
        key="$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-32)"
        ( umask 077; printf '%s\n' "$key" > "$dest/data/owner-claim.key" )
        chmod 600 "$dest/data/owner-claim.key"
        chown "$PANEL_USER:$PANEL_USER" "$dest/data/owner-claim.key"
        _note "setup key (shown once, then claim in the panel): $key"
    fi

    port="$(read_env_value "$dest/.env" "PORT")"
    port="${port:-2095}"

    cat > "$unit" <<UNIT
[Unit]
Description=OVManager panel (install.sh --build dev install)
After=network.target

[Service]
Type=simple
WorkingDirectory=$dest
EnvironmentFile=$dest/.env
Environment="OVM_APP_DIR=$dest"
User=$PANEL_USER
Group=$PANEL_USER
SupplementaryGroups=systemd-journal
ExecStart=$dest/$APP_SLUG
Restart=on-failure
RestartSec=3
$(unit_hardening "$dest" "$dest/data")
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
UNIT
    chmod 644 "$unit"

    systemctl daemon-reload
    systemctl restart "$service"

    health=""
    for _ in $(seq 1 30); do
        if curl -fsS --max-time 2 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
            health=1
            break
        fi
        sleep 1
    done
    [[ -n "$health" ]] || _warn "no /health on port $port yet — check: systemctl status $service"
    _ok "installed $dest (service $service, port $port)"
}


# ── Docker helpers ──────────────────────────────────────────────────────
ensure_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        _note "installing Docker Engine..."
        if command -v apt-get >/dev/null 2>&1; then
            apt-get update -qq >/dev/null 2>&1 || true
            apt-get install -y -qq docker.io docker-compose-plugin >/dev/null 2>&1 \
                || apt-get install -y -qq docker-ce docker-compose-plugin >/dev/null 2>&1 \
                || die "Could not install Docker via apt. Install manually: https://docs.docker.com/engine/install/"
        elif command -v dnf >/dev/null 2>&1; then
            dnf install -y docker docker-compose-plugin >/dev/null 2>&1 || die "Could not install Docker via dnf"
        else
            die "Docker not found. Install it manually: https://docs.docker.com/engine/install/"
        fi
    fi
    command -v docker >/dev/null 2>&1 || die "Docker binary not found"
    docker compose version >/dev/null 2>&1 || docker-compose version >/dev/null 2>&1 \
        || die "Docker Compose v2 is required (docker compose plugin)"
    _ok "Docker present"
}

compose_file() { printf '%s/docker-compose.yml' "$DATA_DIR"; }

write_compose_file() {
    local compose
    compose="$(compose_file)"
    mkdir -p "$DATA_DIR"
    {
        printf 'services:\n'
        printf '  ovmanager:\n'
        printf '    image: %s:%s\n' "$IMAGE_REPO" "$VERSION"
        printf '    container_name: ovmanager\n'
        printf '    restart: unless-stopped\n'
        printf '    network_mode: host\n'
        printf '    environment:\n'
        printf '      HOST: 0.0.0.0\n'
        printf '      PORT: %s\n' "$PORT_VAL"
        printf '      URLPATH: %s\n' "$URLPATH_VAL"
        printf '      ADMIN_USERNAME: %s\n' "$DEFAULT_USER"
        printf '      DATA_DIR: /app/data\n'
        if [[ -n "${OVM_ACME_DOMAIN:-}" ]]; then
            printf '      OVM_ACME_DOMAIN: %s\n' "$OVM_ACME_DOMAIN"
            printf '      SSL_CERTFILE: /app/data/tls/fullchain.pem\n'
            printf '      SSL_KEYFILE: /app/data/tls/privkey.pem\n'
        fi
        printf '    volumes:\n'
        printf '      - %s:/app/data\n' "$DATA_DIR"
        printf '    logging:\n'
        printf '      options:\n'
        printf '        max-size: "5m"\n'
        printf '        max-file: "3"\n'
    } > "$compose"
    chmod 600 "$compose"
    _ok "Compose file written: $compose"
}

setup_docker() {
    ensure_docker
    write_compose_file
    _note "pulling ${IMAGE_REPO}:${VERSION}"
    docker pull "${IMAGE_REPO}:${VERSION}" >/dev/null 2>&1 || _warn "pull failed; continuing with cached image"
    _note "starting container"
    docker compose -f "$(compose_file)" up -d
    _ok "container started"
}

# ── Main install ────────────────────────────────────────────────
do_install() {
    if [[ "$DOCKER" -eq 1 ]]; then
        check_root
        printf '\n  ${_BLUE}OVManager${_RESET} installer  v%s  (docker)\n' "$VERSION" >&2
        printf '  ${_BLUE}────────────────────────────────${_RESET}\n\n' >&2
        _stage "[1/3] Configuration"
        prompt_interactive
        _ok "port=$PORT_VAL  path=$URLPATH_VAL  acme=${OVM_ACME_DOMAIN:-none}"
        _stage "[2/3] Docker"
        setup_docker
        _stage "[3/3] Verification"
        verify_health "$PORT_VAL" "$VERSION" \
            || die "The panel did not report v$VERSION on /health after 40s - docker logs ovmanager"
        _ok "installed v$VERSION via Docker (port $PORT_VAL)"
        return 0
    fi
    local dest="${DEST:-$INSTALL_DIR}"
    [[ -n "$dest" && "$dest" != "/" ]] || die "refusing to operate on '$dest'"
    if [[ -e "$dest" ]]; then
        _note "Already installed at $dest - running update instead"
        do_update "$@"
        return $?
    fi
    check_root
    has_systemd || die "systemd not found — a native install needs it"
    check_deps

    printf '\n  ${_BLUE}OVManager${_RESET} installer  v%s\n' "$VERSION" >&2
    printf '  ${_BLUE}────────────────────────────────${_RESET}\n\n' >&2
    _stage "[1/5] Configuration"
    prompt_interactive
    _ok "port=$PORT_VAL  path=$URLPATH_VAL  acme=${OVM_ACME_DOMAIN:-none}"
    # Check for port conflicts before proceeding
    if is_port_in_use "$PORT_VAL"; then
        _warn "Port $PORT_VAL is already in use. The install may fail."
        if [[ "$INTERACTIVE" -eq 1 ]]; then
            local confirm
            read -r -p "  Continue anyway? [y/N]: " confirm </dev/tty || true
            [[ "$confirm" =~ ^[Yy]$ ]] || die "Installation aborted due to port conflict"
        fi
    fi

    local key port urlpath
    ensure_panel_user
    check_acme_domain
    _stage "[2/5] Download"
    fetch_release "$dest"
    write_env "$dest/.env" "$DATA_DIR" "$dest"
    key="$(mint_claim_key "$DATA_DIR/owner-claim.key")"
    write_systemd_unit "$dest"
    write_backup_units "$dest"
    grant_panel_access "$dest"
    install_cli "$dest"

    _stage "[3/5] Service"
    systemctl daemon-reload
    if systemctl is-active --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then
        systemctl restart "$SYSTEMD_SERVICE" \
            || die "Could not restart $SYSTEMD_SERVICE — journalctl -u $SYSTEMD_SERVICE"
    else
        systemctl enable --now "$SYSTEMD_SERVICE" >/dev/null 2>&1 \
            || die "Could not start $SYSTEMD_SERVICE — journalctl -u $SYSTEMD_SERVICE"
    fi
    enable_backup_timer
    write_acme_renew_units
    enable_acme_renew_timer
    _ok "service $SYSTEMD_SERVICE started"

    port="$(read_env_value "$dest/.env" "PORT")"
    port="${port:-$DEFAULT_PORT}"
    urlpath="$(read_env_value "$dest/.env" "URLPATH")"
    urlpath="${urlpath:-$DEFAULT_URLPATH}"
    _stage "[4/5] Verification"
    verify_health "$port" "$VERSION" \
        || die "The panel did not report v$VERSION on /health after 40s — journalctl -u $SYSTEMD_SERVICE"

    _ok "installed v$VERSION to $dest (service $SYSTEMD_SERVICE, port $port)"

    if [[ -n "${OVM_ACME_DOMAIN:-}" ]]; then
        verify_acme "$DATA_DIR"
    fi

    local display_path="${urlpath#/}"
    display_path="${display_path%/}"
    [[ -n "$display_path" ]] && display_path="/${display_path}/" || display_path="/"

    if [[ -n "$key" ]]; then
        printf '\n  ╔══════════════════════════════════════════════╗\n' >&2
        printf '  ║  ✓  Installation complete                    ║\n' >&2
        printf '  ╠══════════════════════════════════════════════╣\n' >&2
        printf '  ║  URL   http://127.0.0.1:%-21s ║\n' "$port$display_path" >&2
        printf '  ║  Key   %-38s ║\n' "$key" >&2
        local host_ip; host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
        host_ip="${host_ip:-<host>}"
        printf '  ║  SSH   ssh -L %s:127.0.0.1:%s %s  ║\n' "$port" "$port" "$host_ip" >&2
        printf '  ╚══════════════════════════════════════════════╝\n\n' >&2
    else
        _note "existing claim key kept at $DATA_DIR/owner-claim.key"
    fi
}

# ── Update ──────────────────────────────────────────────────────────────
do_update() {
    [[ -x "$INSTALL_DIR/$APP_SLUG" ]] || die "not installed at $INSTALL_DIR — run the installer first"
    exec "$INSTALL_DIR/$APP_SLUG" update "$@"
}

# ── Uninstall ──────────────────────────────────────────────────────────
do_uninstall() {
    local purge=0 dest="${DEST:-$INSTALL_DIR}"
    [[ -n "$dest" && "$dest" != "/" ]] || die "refusing to operate on '$dest'"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --purge) purge=1; shift ;;
            *) die "Unknown option for uninstall: $1" ;;
        esac
    done

    check_root
    # Docker-mode cleanup (best effort)
    if command -v docker >/dev/null 2>&1; then
        if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx 'ovmanager'; then
            docker rm -f ovmanager >/dev/null 2>&1 && _ok "removed container ovmanager" || true
        fi
        rm -f "$(compose_file)" 2>/dev/null || true
    fi
    if [[ -d "$dest" || -f "/etc/systemd/system/$SYSTEMD_SERVICE" ]]; then
        has_systemd || die "systemd not found — a native install needs it"
    fi

    # Stop and disable service
    if systemctl is-active --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then
        systemctl stop "$SYSTEMD_SERVICE"
        _ok "stopped $SYSTEMD_SERVICE"
    fi
    if systemctl is-enabled --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then
        systemctl disable "$SYSTEMD_SERVICE"
        _ok "disabled $SYSTEMD_SERVICE"
    fi

    # Remove systemd units
    for unit in "$SYSTEMD_SERVICE" "${SYSTEMD_SERVICE%.service}-backup.service" "${SYSTEMD_SERVICE%.service}-backup.timer" "${SYSTEMD_SERVICE%.service}-acme-renew.service" "${SYSTEMD_SERVICE%.service}-acme-renew.timer"; do
        if [[ -f "/etc/systemd/system/$unit" ]]; then
            rm -f "/etc/systemd/system/$unit"
            _ok "removed /etc/systemd/system/$unit"
        fi
    done
    systemctl daemon-reload

    # Remove binary and install dirs
    for d in "$INSTALL_DIR" "$dest"; do
        if [[ -d "$d" ]]; then
            rm -rf "$d"
            _ok "removed $d"
        fi
    done

    # Remove CLI link
    if [[ -L "$BIN_DIR/$APP_SLUG" ]]; then
        rm -f "$BIN_DIR/$APP_SLUG"
        _ok "removed $BIN_DIR/$APP_SLUG"
    fi

    # Optionally purge data
    if [[ "$purge" -eq 1 ]]; then
        if [[ -d "$DATA_DIR" ]]; then
            rm -rf "$DATA_DIR"
            _ok "purged $DATA_DIR"
        fi
        # Remove panel user
        if id -u "$PANEL_USER" >/dev/null 2>&1; then
            userdel "$PANEL_USER" 2>/dev/null && _ok "removed user $PANEL_USER" || true
        fi
    else
        _note "data preserved at $DATA_DIR (use --purge to remove)"
    fi

    _ok "OVManager uninstalled"
}

# ── Help / args / main ─────────────────────────────────────────────────
usage() {
    cat <<EOF
OVManager Setup v${VERSION}

USAGE
  bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)

COMMANDS
  update [--version vX.Y.Z]  Hand off to \`ovmanager update\` (staged, with failover)
  uninstall [--purge]        Remove panel, service, and CLI (data kept unless --purge)
  version-script             Print this installer's version and commit
  help                       Show this help

OPTIONS
  -i, --interactive          Ask for port, URL path, and optional Let's Encrypt domain
  -y, --yes                  Accept defaults without prompts (CI-friendly)
  --acme DOMAIN              Request a Let's Encrypt certificate for DOMAIN
                             (HTTP-01; port 80 must reach this server). Same as
                             pre-setting OVM_ACME_DOMAIN in the environment.
                             On failure the install continues on plain HTTP.
  --build [DIR]              Dev install from a working tree (default: the
                             current directory): rsync + go build + a dev unit,
                             no release fetch. (--from-source is a deprecated
                             alias.)
  --dest DIR                 with --build: destination (default /opt/ovmanager)
  --docker                   Install/run via Docker instead of a native systemd service
  -h, --help                 Show this help

ENVIRONMENT
  OVM_ACME_DOMAIN=<domain>   Same as --acme DOMAIN: after first start the panel
                             issues a Let's Encrypt certificate over HTTP-01
                             and renews automatically (T-30 days). The install
                             never dies over issuance; it warns and the panel
                             keeps serving plain HTTP until it works.
  OVM_PORT=<port>            Override default port (default: 2095)
  OVM_URLPATH=<path>         Override default URL path (default: dashboard)
  OVM_REPO=<owner/repo>      Use a different GitHub repository
  OVM_BIN_DIR=<dir>          Override CLI binary directory (default: /usr/local/bin)
  OVM_PANEL_USER=<user>      Override panel service user (default: ovmanager)
  OVM_HEALTH_TIMEOUT=<sec>   Health check timeout in seconds (default: 40)
  OVM_ACME_TIMEOUT=<sec>     ACME certificate wait timeout in seconds (default: 60)

After installation, use ovmanager for status, service controls,
logs, backups, HTTPS, diagnostics, recovery and updates.

EXIT
  0 ok   1 error   130 interrupted
EOF
    exit 0
}

script_commit() {
    local dir candidate
    dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || { printf 'unknown'; return 0; }
    candidate="$dir"
    while [[ -n "$candidate" && "$candidate" != "/" ]]; do
        if [[ -e "$candidate/.git" ]]; then
            git -C "$candidate" rev-parse --short HEAD 2>/dev/null || printf 'unknown'
            return 0
        fi
        candidate="$(dirname -- "$candidate")"
    done
    printf 'unknown'
}

print_version_script() {
    local commit
    commit="$(script_commit)"
    printf 'installer  v%s\n' "$VERSION"
    if [[ "$commit" == "unknown" ]]; then
        printf 'commit     unknown — not a git checkout (downloaded installer)\n'
    else
        printf 'commit     %s\n' "$commit"
    fi
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --build|--from-source) FROM_SOURCE=1; shift
                                   if [[ $# -ge 1 && "$1" != -* ]]; then SRC="$1"; shift; fi ;;
            --acme)        [[ $# -ge 2 ]] || die "--acme needs a domain"; OVM_ACME_DOMAIN="$2"; shift 2 ;;
            --dest)        [[ $# -ge 2 ]] || die "--dest needs a directory"; DEST="$2"; shift 2 ;;
            -i|--interactive) INTERACTIVE=1; shift ;;
            --docker)         DOCKER=1; shift ;;
            -y|--yes)         YES=1; shift ;;
            -h|--help)     usage ;;
            help)          usage ;;
            version-script|script-version) ACTION="version-script"; shift ;;
            update)        ACTION="update"; shift; UPDATE_ARGS=("$@"); break ;;
            uninstall)     ACTION="uninstall"; shift; UPDATE_ARGS=("$@"); break ;;
            install|interactive) shift ;;
            *)             die "Unknown option: $1  (see --help)" ;;
        esac
    done
}

main() {
    parse_args "$@"
    case "$ACTION" in
        version-script) print_version_script; return 0 ;;
        update)         do_update "${UPDATE_ARGS[@]}" ;;
        uninstall)      do_uninstall "${UPDATE_ARGS[@]}"; return 0 ;;
    esac
    if [[ "$FROM_SOURCE" -eq 1 ]]; then
        do_from_source
    else
        do_install
    fi
}

main "$@"