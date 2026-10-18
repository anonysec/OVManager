#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# OVManager installer — bootstraps the Go binary.
#
# The panel and the `ovm` operator CLI are one Go binary with the built SPA
# embedded, so a release ships bare per-platform binaries. A default install
# fetches the checksummed binary for this platform straight into $INSTALL_DIR,
# writes the systemd unit, restarts, and verifies /health reports the release
# version. That last check
# is the v1.6.0 gap: the old verify did not restart the service and probed a
# dev layout, so a release that never came up still reported success.
#
# Zero-question by default:
#   bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
#
# Dev install from a working tree (rsync + go build + a dev unit):
#   ./install.sh --from-source [DIR] [--dest DIR]
#
# No owner password is set here: the install prints a one-time claim key and
# the operator claims the panel in the browser. Day-to-day operations (status,
# logs, backup, restore, TLS, recovery, update) live in the `ovm` binary.
#
set -Eeuo pipefail

# Forks: point release downloads (and update pulls) at your own repo.
REPO="${OVM_REPO:-anonysec/OVManager}"
APP_SLUG="ovmanager"
INSTALL_DIR="/opt/ovmanager"
DATA_DIR="/var/lib/ovmanager"
DEFAULT_PORT=2095
DEFAULT_USER="admin"
SYSTEMD_SERVICE="ovmanager.service"
# Keep in sync with internal/version/version.go: the installer fetches this
# release tag, and the /health check requires the running binary to report it.
VERSION="2.1.2"
BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"

# The panel runs as an unprivileged service account on a native install: it is
# a server parsing untrusted input from anyone who can reach the port, so as
# root a remote compromise of the panel would be a compromise of the box. It
# needs only its own code, its .env, its data dir and the TLS key, and cannot
# update itself because `ovm update` replaces the tree and restarts the unit.
PANEL_USER="${OVM_PANEL_USER:-ovmanager}"
CLI_NAME="ovmanager"
CLI_ALIAS="ovm"

_ok()   { printf '  ok    %s\n' "$*" >&2; }
_note() { printf '  ..    %s\n' "$*" >&2; }
_warn() { printf '  warn  %s\n' "$*" >&2; }
die()   { printf 'install: error: %s\n' "$*" >&2; exit 1; }

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

# ── Release fetch ──────────────────────────────────────────────────────
# Release assets are bare per-platform binaries (the built SPA is embedded in
# the binary), each with a .sha256 sidecar. Map the machine's arch onto the
# asset suffix release.yml publishes.
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

# fetch_release <dir>: download this platform's binary and its sha256 sidecar,
# verify, then install it as $APP_SLUG under <dir>. No archive, no extract.
fetch_release() {
    local dest="$1" work asset
    asset="$(release_asset)"
    work="$(mktemp -d)"
    _note "fetching v$VERSION ($asset)"
    curl -fsSL -o "$work/$asset" "$(release_url)" \
        || { rm -rf "$work"; die "No release file for v$VERSION — see https://github.com/$REPO/releases"; }
    curl -fsSL -o "$work/$asset.sha256" "$(release_checksum_url)" \
        || { rm -rf "$work"; die "Release checksum file is missing for v$VERSION"; }
    ( cd "$work" && sha256sum -c "$asset.sha256" >/dev/null ) \
        || { rm -rf "$work"; die "Release checksum mismatch for v$VERSION"; }
    mkdir -p "$dest"
    install -m 0755 "$work/$asset" "$dest/$APP_SLUG"
    chown root:root "$dest/$APP_SLUG"
    rm -rf "$work"
    _ok "installed v$VERSION to $dest"
}

# ── Configuration ──────────────────────────────────────────────────────
read_env_port() {  # read_env_port <envfile> → the PORT it sets
    local envfile="$1" p
    p="$(awk -F= '/^PORT=/{print $2; exit}' "$envfile" 2>/dev/null | tr -d '[:space:]')"
    printf '%s' "${p:-$DEFAULT_PORT}"
}

# write_env <envfile> <data_dir>: create once, never overwrite. A rerun must
# not rotate the operator's config, so an existing file is only re-tightened.
write_env() {
    local envfile="$1" data_dir="$2"
    if [[ -f "$envfile" ]]; then
        chmod 600 "$envfile" 2>/dev/null || true
        return 0
    fi
    # No credential here, ever: the owner is a row in the panel database. The
    # install prints a one-time claim key instead, and the browser turns it into
    # the bcrypt row.
    (
    umask 077
    {
        printf 'HOST=0.0.0.0\n'
        printf 'PORT=%s\n' "$DEFAULT_PORT"
        printf 'URLPATH=\n'
        printf 'ADMIN_USERNAME=%s\n' "$DEFAULT_USER"
        printf 'DATA_DIR=%s\n' "$data_dir"
        if [[ -n "${OVM_ACME_DOMAIN:-}" ]]; then
            # One-click TLS at bootstrap: the panel issues a Let's Encrypt
            # certificate over HTTP-01 shortly after first start (daily worker),
            # writing this declared pair. The paths live under DATA_DIR so the
            # unprivileged panel account can write them.
            printf 'SSL_CERTFILE=%s/tls/fullchain.pem\n' "$data_dir"
            printf 'SSL_KEYFILE=%s/tls/privkey.pem\n' "$data_dir"
            printf 'OVM_ACME_DOMAIN=%s\n' "$OVM_ACME_DOMAIN"
        fi
    } > "$envfile"
    )
    chmod 600 "$envfile"
    _note "$envfile"
}

# mint_claim_key <path>: create once and print it. A rerun must never
# invalidate the key a live panel is still holding for its owner claim.
mint_claim_key() {
    local path="$1" key
    mkdir -p "$(dirname "$path")"
    if [[ -f "$path" ]]; then
        return 0
    fi
    key="$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-32)"
    ( umask 077; printf '%s\n' "$key" > "$path" )
    chmod 600 "$path"
    printf '%s\n' "$key"
}

# ── Service ────────────────────────────────────────────────────────────
# check_acme_domain validates the operator's OVM_ACME_DOMAIN early. Fail-soft:
# an invalid domain is a warning and a plain-HTTP install, never a dead run.
check_acme_domain() {
    [[ -z "${OVM_ACME_DOMAIN:-}" ]] && return 0
    if [[ "$OVM_ACME_DOMAIN" != *[!A-Za-z0-9.-]* && "$OVM_ACME_DOMAIN" == *.* ]]; then
        _ok "acme    Let's Encrypt issuance scheduled for $OVM_ACME_DOMAIN"
        return 0
    fi
    _warn "OVM_ACME_DOMAIN '$OVM_ACME_DOMAIN' is not a valid DNS name — issuing is skipped, the panel stays on plain HTTP"
    OVM_ACME_DOMAIN=""
}

# verify_acme <data_dir>: the panel's worker issues shortly after first start.
# Poll up to 3 minutes for the declared pair; a miss is a warning and the
# panel keeps serving plain HTTP. The certificate must parse and hold at
# least one day — otherwise the pair cannot terminate TLS anywhere.
verify_acme() {
    local data_dir="$1" cert key i check
    cert="$data_dir/tls/fullchain.pem"
    key="$data_dir/tls/privkey.pem"
    _note "waiting for the Let's Encrypt certificate (up to 180s)…"
    for ((i = 0; i < 60; i++)); do
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

ensure_panel_user() {
    mkdir -p "$DATA_DIR"
    id -u "$PANEL_USER" >/dev/null 2>&1 && return 0
    useradd --system --no-create-home --home-dir "$DATA_DIR" \
        --shell /usr/sbin/nologin \
        --comment "OVManager panel service account" "$PANEL_USER" >/dev/null 2>&1 \
        || die "Could not create the $PANEL_USER account"
}

write_systemd_unit() {
    cat > "/etc/systemd/system/$SYSTEMD_SERVICE" <<UNIT
[Unit]
Description=OVManager OpenVPN Panel
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
Environment="OVM_APP_DIR=$INSTALL_DIR"
User=$PANEL_USER
Group=$PANEL_USER
ExecStart=$INSTALL_DIR/$APP_SLUG
Restart=on-failure
RestartSec=3
# The built-in ACME client binds the standalone HTTP-01 listener on port 80
# only during issuance; the bind must work even though the panel runs as
# $PANEL_USER.
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
UNIT
    chmod 644 "/etc/systemd/system/$SYSTEMD_SERVICE"
}

# A daily verified backup, independent of the panel being up: a system timer
# that runs `ovm backup --keep 7`. Retention mirrors the CLI default (7, vs the
# 14 default for manual runs) so disk stays bounded under automation.
write_backup_units() {
    cat > "/etc/systemd/system/${SYSTEMD_SERVICE%.service}-backup.service" <<UNIT
[Unit]
Description=OVManager daily backup
After=${SYSTEMD_SERVICE}

[Service]
Type=oneshot
EnvironmentFile=$INSTALL_DIR/.env
User=$PANEL_USER
Group=$PANEL_USER
ExecStart=$INSTALL_DIR/$APP_SLUG backup --keep 7
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

enable_backup_timer() {
    systemctl daemon-reload
    systemctl enable --now "${SYSTEMD_SERVICE%.service}-backup.timer" >/dev/null 2>&1 \
        || _warn "Could not enable the backup timer (enable it with: systemctl enable --now ${SYSTEMD_SERVICE%.service}-backup.timer)"
}

# The panel user must be able to read the code and the config, and to write its
# data dir — and nothing else. The .env stays root-owned and group-readable so
# the config never lands in a file the panel user owns (and could rewrite).
grant_panel_access() {
    chmod 755 "$INSTALL_DIR"
    chmod 755 "$INSTALL_DIR/$APP_SLUG"
    mkdir -p "$DATA_DIR"
    chown -R "$PANEL_USER:$PANEL_USER" "$DATA_DIR"
    chmod 700 "$DATA_DIR"
    chown "root:$PANEL_USER" "$INSTALL_DIR/.env"
    chmod 640 "$INSTALL_DIR/.env"
}

install_cli() {
    mkdir -p "$BIN_DIR" 2>/dev/null || { _warn "Could not create $BIN_DIR"; return 0; }
    if ln -sf "$INSTALL_DIR/$APP_SLUG" "$BIN_DIR/$CLI_NAME" \
        && ln -sf "$CLI_NAME" "$BIN_DIR/$CLI_ALIAS"; then
        _ok "command  $BIN_DIR/$CLI_NAME  (alias: $CLI_ALIAS)"
    else
        _warn "Could not install the $CLI_NAME command into $BIN_DIR"
    fi
}

# verify_health <port> <expected-version>: poll the loopback /health until the
# running binary reports the version we installed. The version match is the
# point: an answer from a stale process (the v1.6.0 dev-layout gap) must fail,
# not pass as "healthy".
verify_health() {
    local port="$1" want="$2" i body got
    for ((i = 0; i < 40; i++)); do
        body="$(curl -fsS --max-time 3 "http://127.0.0.1:${port}/health" 2>/dev/null || true)"
        if [[ -n "$body" ]]; then
            got="$(printf '%s' "$body" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)"
            if [[ "$got" == "$want" ]]; then
                _ok "health  v$got on port $port"
                return 0
            fi
            [[ -n "$got" ]] && _warn "health reports '$got', expected '$want'"
        fi
        sleep 1
    done
    return 1
}

# Dev install from a working tree (--from-source [DIR]). Validate src -> rsync
# to dest -> build the binary -> minimal .env and unit -> restart -> loopback
# health. Rerunning updates in place; dev-only (no release fetch, no update
# transaction).
#
# The unit name is derived from DEST, so a test --dest (e.g. /tmp/...) writes
# its own unit and can never clobber /etc/systemd/system/ovmanager.service on a
# box that already runs a panel.
do_from_source() {
    local src="${SRC:-$PWD}" dest="${DEST:-$INSTALL_DIR}"
    local service unit port key health

    # Validation runs before the root gate so a broken tree reports its real
    # reason, and --help/bad flags work for whoever ran them.
    [[ -d "$src" ]] || die "no source directory: $src"
    [[ -f "$src/cmd/main.go" ]] || die "no Go source tree in $src (cmd/main.go missing)"
    [[ -d "$src/web/dist" ]] || die "web/dist missing in $src — run: cd web && npm run build"

    check_root
    # rm -rf and a --delete rsync live behind this: an empty or / destination is
    # never intended.
    [[ -n "$dest" && "$dest" != "/" ]] || die "refusing to operate on '$dest'"
    command -v rsync >/dev/null || die "rsync not found"
    command -v go >/dev/null || die "go not found — install Go 1.27+ (https://go.dev/dl/)"

    dest="${dest%/}"
    service="$(basename "$dest").service"
    unit="/etc/systemd/system/$service"

    # .env is excluded so a dest credential file is never overwritten by a
    # rerun (--delete alone would not touch an excluded file).
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

    # The binary is the service: build it in place so the unit can ExecStart it.
    # Stage the built SPA into the embed package first — this mirrors `make
    # build`, the only step the release path does not need (its dist ships
    # pre-embedded).
    mkdir -p "$dest/internal/webfs/dist"
    cp -a "$dest/web/dist/." "$dest/internal/webfs/dist/"
    ( cd "$dest" && go build -o "$APP_SLUG" ./cmd )

    mkdir -p "$dest/data"
    # Never copy the source tree's .env: dev trees carry real credentials. This
    # one is kept across reruns and never overwritten.
    if [[ ! -f "$dest/.env" ]]; then
        cat > "$dest/.env" <<EOF
# Generated by install.sh --from-source. Kept across reruns, never overwritten.
PORT=2095
DATA_DIR=$dest/data
ADMIN_USERNAME=admin
EOF
    fi
    chmod 600 "$dest/.env"
    # Claim key is create-once like .env: reruns must never invalidate it.
    if [[ ! -f "$dest/data/owner-claim.key" ]]; then
        key="$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-32)"
        ( umask 077; printf '%s\n' "$key" > "$dest/data/owner-claim.key" )
        chmod 600 "$dest/data/owner-claim.key"
        _note "setup key (shown once, then claim in the panel): $key"
    fi
    port="$(read_env_port "$dest/.env")"

    cat > "$unit" <<UNIT
[Unit]
Description=OVManager panel (install.sh --from-source dev install)
After=network.target

[Service]
Type=simple
WorkingDirectory=$dest
EnvironmentFile=$dest/.env
Environment="OVM_APP_DIR=$dest"
ExecStart=$dest/$APP_SLUG
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl restart "$service"

    # Fail open: a slow panel is a warning, not a failed install.
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

do_install() {
    [[ -e "$INSTALL_DIR" || -f "/etc/systemd/system/$SYSTEMD_SERVICE" ]] \
        && die "Already installed ($INSTALL_DIR). Use: ovm update"
    check_root
    has_systemd || die "systemd not found — a native install needs it"
    check_deps

    local key port
    ensure_panel_user
    check_acme_domain
    fetch_release "$INSTALL_DIR"
    write_env "$INSTALL_DIR/.env" "$DATA_DIR"
    key="$(mint_claim_key "$DATA_DIR/owner-claim.key")"
    write_systemd_unit
    write_backup_units
    grant_panel_access

    systemctl daemon-reload
    systemctl enable --now "$SYSTEMD_SERVICE" >/dev/null 2>&1 \
        || die "Could not start $SYSTEMD_SERVICE — journalctl -u $SYSTEMD_SERVICE"
    enable_backup_timer

    port="$(read_env_port "$INSTALL_DIR/.env")"
    verify_health "$port" "$VERSION" \
        || die "The panel did not report v$VERSION on /health after 40s — journalctl -u $SYSTEMD_SERVICE"

    install_cli
    _ok "installed v$VERSION to $INSTALL_DIR (service $SYSTEMD_SERVICE, port $port)"
    if [[ -n "${OVM_ACME_DOMAIN:-}" ]]; then
        verify_acme "$DATA_DIR"
    fi
    if [[ -n "$key" ]]; then
        printf '\n  Open  http://<host>:%s/  and claim the panel with this key:\n\n      %s\n\n' \
            "$port" "$key" >&2
    else
        _note "existing claim key kept at $DATA_DIR/owner-claim.key"
    fi
}

# `install.sh update` is what the panel's own updater execs (panel/updater.go).
# The transaction lives in the binary now, so this is a hand-off, not a second
# implementation.
do_update() {
    [[ -x "$INSTALL_DIR/$APP_SLUG" ]] || die "not installed at $INSTALL_DIR — run the installer first"
    exec "$INSTALL_DIR/$APP_SLUG" update "$@"
}

# ── Help / args / main ─────────────────────────────────────────────────
usage() {
    cat <<EOF
OVManager Setup v${VERSION}

USAGE
  bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)

COMMANDS
  update [--version vX.Y.Z]  Hand off to \`ovm update\` (staged, with failover)
  version-script             Print this installer's version and commit
  help                       Show this help

OPTIONS
  --acme DOMAIN              Request a Let's Encrypt certificate for DOMAIN
                             (HTTP-01; port 80 must reach this server). Same as
                             pre-setting OVM_ACME_DOMAIN in the environment.
                             On failure the install continues on plain HTTP.
  --from-source [DIR]        Dev install from a working tree (default: the
                             current directory): rsync + go build + a dev unit,
                             no release fetch
  --dest DIR                 with --from-source: destination (default /opt/ovmanager)
  -y, --yes                  Accept all defaults (the bootstrap never prompts)
  -h, --help                 Show this help

ENVIRONMENT
  OVM_ACME_DOMAIN=<domain>   Same as --acme DOMAIN: after first start the panel
                             issues a Let's Encrypt certificate over HTTP-01
                             and renews automatically (T-30 days). The install
                             never dies over issuance; it warns and the panel
                             keeps serving plain HTTP until it works.

After installation, use ovm (alias: ovmanager) for status, service controls,
logs, backups, HTTPS, diagnostics, recovery and updates.

EXIT
  0 ok   1 error   130 interrupted
EOF
    exit 0
}

# `version-script`: which installer did you actually run? VERSION is embedded; a
# commit only exists when this file sits in a git checkout.
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

FROM_SOURCE=0 SRC="" DEST=""
ACTION="install"
UPDATE_ARGS=()

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --from-source) FROM_SOURCE=1; shift
                           if [[ $# -ge 1 && "$1" != -* ]]; then SRC="$1"; shift; fi ;;
            --acme)        [[ $# -ge 2 ]] || die "--acme needs a domain"; OVM_ACME_DOMAIN="$2"; shift 2 ;;
            --dest)        [[ $# -ge 2 ]] || die "--dest needs a directory"; DEST="$2"; shift 2 ;;
            -y|--yes)      shift ;;
            -h|--help)     usage ;;
            help)          usage ;;
            version-script|script-version) ACTION="version-script"; shift ;;
            update)        ACTION="update"; shift; UPDATE_ARGS=("$@"); break ;;
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
    esac
    if [[ "$FROM_SOURCE" -eq 1 ]]; then
        do_from_source
    else
        do_install
    fi
}

main "$@"
