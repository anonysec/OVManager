#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# OVManager installer — native (systemd) or Docker.
#
# Zero-question by default: bare run installs with safe generated values.
#   bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
#
# Interactive wizard:
#   bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) interactive
#
# AI / CI (never prompts):
#   curl -sSL URL | sudo bash -s -- -y --mode native -p 'SECRET'
#
# Day-to-day operations (status, logs, backup, TLS, recovery) live in the
# manager: ovm  (installed as ovmanager/ovm).
#
set -Eeuo pipefail

# Forks: point source downloads (and update pulls) at your own repo.
REPO="${OVM_REPO:-anonysec/OVManager}"
APP_SLUG="ovmanager"
BRANCH="main"
# Production installs use only signed/checksummed release artifacts. Developers
# who need a source checkout use git and the contributor documentation.
INSTALL_DIR="/opt/ovmanager"
DATA_DIR="/var/lib/ovmanager"
DEFAULT_PORT=2095
DEFAULT_USER="admin"
SYSTEMD_SERVICE="ovmanager.service"
VERSION="1.0.9"
IMAGE_REPO="ghcr.io/${REPO,,}"
ACTIVE_IMAGE_VERSION="$VERSION"
# Terminal command installed by install_cli() (copy of the manager).
BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"
CLI_NAME="ovmanager"
CLI_ALIAS="ovm"

# ── Colour / TTY ───────────────────────────────────────────────────────
# SYNC: mirrors scripts/lib/*.sh (curl-pipe installs run standalone).
NC=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'
WH=$'\033[97m'; GR=$'\033[32m'; RD=$'\033[31m'
YL=$'\033[33m'; CY=$'\033[36m'; GY=$'\033[90m'
OR=$'\033[38;5;208m'
[[ -t 1 && -z "${NO_COLOR:-}" ]] || { NC=''; B=''; D=''; WH=''; GR=''; RD=''; YL=''; CY=''; GY=''; OR=''; }

line()  { printf '  %b\n' "$*" >&2; }
step()  { line "${GR}✓${NC}  $*"; }
info()  { line "${OR}→${NC}  $*"; }
warn()  { line "${YL}!${NC}  $*"; }
fail()  { line "${RD}✗${NC}  $*"; }
kv()    { printf '  %b%-14s%b %b\n' "$GY" "$1" "$NC" "$2" >&2; }
hr()    { line "${GY}──────────────────────────────────────────────${NC}"; }

die() {
    local run_id="${OVM_RUN_ID:-$(date +%Y%m%d-%H%M%S)-$$}"
    printf '\n  %bError:%b %s\n  %bRun ID:%b %s\n\n' "$RD" "$NC" "$1" "$GY" "$NC" "$run_id" >&2
    exit 1
}
trap 'printf "\n  %bInterrupted.%b\n" "$RD" "$NC" >&2; exit 130' INT TERM
# Pinpoint trap: any future failure (real or environmental) reports the exact
# command and line instead of surfacing as a mystery message elsewhere.
trap 'warn "Command failed near line $LINENO (running: ${BASH_COMMAND:0:80})"' ERR

# ── Flags (defaults) ───────────────────────────────────────────────────
PORT="" PATHPREFIX="" ADMIN_USER="" ADMIN_PASS=""
TLS_MODE="" TLS_DOMAIN="" TLS_KEY="" TLS_CERT=""
PUBLIC_URL="" MODE="" ACTION="install" PIN=""
YES=0 PURGE=0 JSON=0 DRY=0 GENERATED_PASS=0 PATH_SET=0
CLI_GIVEN=0 EXPRESS=0
OPERATION_LOCK="${DATA_DIR}/.operation.lock"
OPERATION_LOCK_HELD=0
UPDATE_STATE="${DATA_DIR}/update-state.json"
UPDATE_MARKER="${DATA_DIR}/update-maintenance"
UPDATE_STAGE="$(dirname "$INSTALL_DIR")/.${APP_SLUG}.staging"
UPDATE_PREVIOUS="$(dirname "$INSTALL_DIR")/.${APP_SLUG}.previous"

update_state() {
    local phase="$1" from="${2:-unknown}" target="${3:-$VERSION}" backup="${4:-}"
    mkdir -p "$DATA_DIR"
    python3 - "$UPDATE_STATE" "$phase" "$from" "$target" "$backup" <<'PY'
import json, os, sys, tempfile, time
path, phase, old, target, backup = sys.argv[1:]
data = {"phase": phase, "from_version": old, "to_version": target,
        "safety_backup": backup or None, "updated_at": int(time.time()), "pid": os.getppid()}
fd, tmp = tempfile.mkstemp(prefix=".update-state-", dir=os.path.dirname(path))
try:
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2); f.write("\n"); f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, 0o600); os.replace(tmp, path)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
PY
}

update_safety_backup() {
    local keep=10 path
    # Try the installed tree's transactional backup first; any failure
    # (missing module, older signature) falls back to a legacy bundle so
    # updates from old releases are never blocked.
    if [[ "$MODE" == "docker" ]]; then
        if path="$(docker exec ovmanager /app/.venv/bin/python -c \
            "from backend.routers.maintenance import create_panel_backup; p=create_panel_backup(${keep}, label='pre-update'); print(p or '')" 2>/dev/null)"; then
            # The backup is created through the /app/data bind mount. Journal the
            # host path so reboot recovery can verify and restore it.
            printf '%s\n' "${path/#\/app\/data/$DATA_DIR}"
            return 0
        fi
    else
        if path="$( ( cd "$INSTALL_DIR" && .venv/bin/python -c \
            "from backend.routers.maintenance import create_panel_backup; p=create_panel_backup(${keep}, label='pre-update'); print(p or '')" 2>/dev/null) )"; then
            printf '%s\n' "$path"
            return 0
        fi
    fi
    warn "Installed release lacks transactional backups — legacy safety bundle"
    # Installed release predates transactional backups: build an equivalent
    # .ovmbak with stdlib python so updates from old releases are not
    # blocked. restore_update_database consumes both variants unchanged.
    legacy_safety_bundle "${1:-unknown}" || return 1
}

legacy_safety_bundle() {
    local app_version="$1" backup_dir="${DATA_DIR}/backups"
    [[ -f "${DATA_DIR}/ovmanager.db" ]] || return 0
    mkdir -p "$backup_dir" && chmod 700 "$backup_dir"
    python3 - "$DATA_DIR" "$backup_dir" "$app_version" <<'PY' || return 1
import hashlib, json, os, sqlite3, sys, tarfile, tempfile
from datetime import datetime, timezone
data_dir, backup_dir, app_version = sys.argv[1], sys.argv[2], sys.argv[3]
src = os.path.join(data_dir, "ovmanager.db")
con = sqlite3.connect("file:%s?mode=ro" % src, uri=True)
try:
    row = con.execute("PRAGMA quick_check").fetchone()
finally:
    con.close()
if not row or row[0] != "ok":
    raise SystemExit("source database integrity failed")
fd, snap = tempfile.mkstemp(prefix=".ovmanager-snapshot-", suffix=".db", dir=backup_dir)
os.close(fd); os.chmod(snap, 0o600)
s = sqlite3.connect("file:%s?mode=ro" % src, uri=True)
d = sqlite3.connect(snap)
try:
    s.backup(d)
finally:
    d.close(); s.close()
digest = hashlib.sha256()
with open(snap, "rb") as f:
    for chunk in iter(lambda: f.read(1048576), b""):
        digest.update(chunk)
digest = digest.hexdigest()
now = datetime.now(timezone.utc)
manifest = {"format": "ovmanager-backup", "format_version": 1,
            "app_version": app_version, "created_at": now.isoformat(),
            "database": "panel.db", "database_sha256": digest}
stamp = now.strftime("%Y%m%d_%H%M%S")
final = os.path.join(backup_dir, "ovmanager-pre-update-%s-v1.ovmbak" % stamp)
fd, tmp = tempfile.mkstemp(prefix=".ovmanager-backup-", suffix=".part", dir=backup_dir)
os.close(fd); os.chmod(tmp, 0o600)
try:
    with tempfile.TemporaryDirectory(prefix="ovmanager-bundle-") as stage:
        with open(os.path.join(stage, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, sort_keys=True, indent=2); f.write("\n")
        with open(os.path.join(stage, "checksums.sha256"), "w", encoding="ascii") as f:
            f.write("%s  panel.db\n" % digest)
        with tarfile.open(tmp, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            archive.add(snap, arcname="panel.db", recursive=False)
            archive.add(os.path.join(stage, "manifest.json"), arcname="manifest.json", recursive=False)
            archive.add(os.path.join(stage, "checksums.sha256"), arcname="checksums.sha256", recursive=False)
    with tarfile.open(tmp, "r:gz") as archive:
        names = {m.name for m in archive.getmembers() if m.isfile()}
        if names != {"panel.db", "manifest.json", "checksums.sha256"}:
            raise SystemExit("bundle verification failed")
        data = archive.extractfile("panel.db").read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise SystemExit("bundle checksum mismatch")
    os.replace(tmp, final); os.chmod(final, 0o600)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
    try: os.unlink(snap)
    except FileNotFoundError: pass
print(final)
PY
    # Retention for legacy pre-update bundles (backend prunes only its own).
    ls -t "$backup_dir"/ovmanager-pre-update-*.ovmbak 2>/dev/null | tail -n +11 | xargs -r rm -f
    return 0
}

# True when the live database no longer matches the safety bundle (schema
# version): the candidate migrated it, so failover must restore. When the
# versions match the candidate never migrated and failover skips the
# restore. A missing/unreadable live database also requests a restore.
# Version reported by the candidate. Native: loopback /health discloses it.
# Docker: host-side requests never see a version (loopback-only disclosure),
# so read it from inside the container — its filesystem IS the staged image,
# and wait_health already proved the process answers.
candidate_version() {
    if [[ "$MODE" == "docker" ]]; then
        docker exec ovmanager /app/.venv/bin/python -c \
            "from backend.version import __version__; print(__version__)" 2>/dev/null || true
    else
        curl -fskS --max-time 5 "${scheme}://127.0.0.1:${PORT}/health" 2>/dev/null \
            | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true
    fi
}

db_restore_needed() {
    python3 - "$1" "${DATA_DIR}/ovmanager.db" <<'PY'
import os, sqlite3, sys, tarfile, tempfile
bundle, live = sys.argv[1], sys.argv[2]
def version(path):
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        return con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()
try:
    live_version = version(live)
except Exception:
    raise SystemExit(0)
with tarfile.open(bundle, "r:gz") as tf:
    data = tf.extractfile("panel.db").read()
fd, tmp = tempfile.mkstemp(prefix=".update-compare-")
try:
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    bundle_version = version(tmp)
finally:
    os.unlink(tmp)
raise SystemExit(0 if bundle_version != live_version else 1)
PY
}

restore_update_database() {
    local bundle="$1" db="${2:-${DATA_DIR}/ovmanager.db}"
    [[ -f "$bundle" ]] || return 1
    python3 - "$bundle" "$db" <<'PY'
import hashlib, json, os, tarfile, tempfile, sys
bundle, db = sys.argv[1:]
with tarfile.open(bundle, "r:gz") as tf:
    names = {m.name for m in tf.getmembers() if m.isfile()}
    if names != {"panel.db", "manifest.json", "checksums.sha256"}:
        raise SystemExit("unsafe update backup")
    manifest = json.load(tf.extractfile("manifest.json"))
    checksum_line = tf.extractfile("checksums.sha256").read().decode("ascii").strip()
    data = tf.extractfile("panel.db").read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != manifest.get("database_sha256") or checksum_line != f"{digest}  panel.db":
        raise SystemExit("update backup checksum mismatch")
parent = os.path.dirname(db); fd, tmp = tempfile.mkstemp(prefix=".update-rollback-", dir=parent)
try:
    try:
        current = os.stat(db); mode = current.st_mode & 0o777; owner = (current.st_uid, current.st_gid)
    except FileNotFoundError:
        mode = 0o600; owner = None
    with os.fdopen(fd, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, mode)
    if owner is not None: os.chown(tmp, *owner)
    os.replace(tmp, db)
    for suffix in ("-wal", "-shm"):
        try: os.unlink(db + suffix)
        except FileNotFoundError: pass
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
PY
}

operation_begin() {
    local name="$1" owner=""
    mkdir -p "$DATA_DIR"
    if ! mkdir "$OPERATION_LOCK" 2>/dev/null; then
        owner="$(cat "$OPERATION_LOCK/pid" 2>/dev/null || true)"
        if [[ "$owner" =~ ^[0-9]+$ ]] && ! kill -0 "$owner" 2>/dev/null; then
            warn "Removing stale operation lock from process $owner"
            rm -rf "$OPERATION_LOCK"
            mkdir "$OPERATION_LOCK" || die "Another maintenance operation is running"
        else
            die "Another maintenance operation is running${owner:+ (process $owner)}. Try again later."
        fi
    fi
    printf '%s\n' "$$" > "$OPERATION_LOCK/pid"
    printf '%s\n' "$name" > "$OPERATION_LOCK/action"
    chmod 700 "$OPERATION_LOCK"
    OPERATION_LOCK_HELD=1
}

operation_end() {
    [[ "$OPERATION_LOCK_HELD" -eq 1 ]] || return 0
    rm -rf "$OPERATION_LOCK"
    OPERATION_LOCK_HELD=0
}

trap operation_end EXIT

[[ "${CI:-}" == "true" || "${NONINTERACTIVE:-}" == "1" ]] && YES=1

is_port() { [[ "$1" =~ ^[0-9]+$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )); }

rand_path() {
    openssl rand -hex 4 2>/dev/null || head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

rand_pass() {
    openssl rand -base64 12 2>/dev/null | tr -d '/+=\n' | head -c 12
}

rand_hex() {
    openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

# Interactive if the operator did not pass -y AND we can talk to a terminal.
# `curl | bash` has no stdin TTY; humans still work via /dev/tty.
# AI / CI must pass -y (or CI=true) so this never blocks on a prompt.
can_prompt() {
    [[ "${YES:-0}" -eq 0 ]] || return 1
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
    [[ "${YES:-0}" -eq 1 ]] && return 0
    can_prompt || return 0
    printf '  %s [%bY%b/n] : ' "$1" "$GR" "$NC" >&2
    local c=""
    c="$(_read_reply)" || true
    [[ ! "$c" =~ ^[Nn]$ ]]
}

# Explicit-yes prompt (default NO): used for destructive extras like deleting
# data during uninstall. Non-interactive runs keep the safe answer.
confirm_no() {
    [[ "${YES:-0}" -eq 1 ]] && return 1
    can_prompt || return 1
    printf '  %s [y/%bN%b] : ' "$1" "$GR" "$NC" >&2
    local c=""
    c="$(_read_reply)" || true
    [[ "$c" =~ ^[Yy]$ ]]
}

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
        if [[ $rc -eq 0 ]]; then step "$msg"; else fail "$msg"; return 1; fi
    else
        info "$msg"
        "$@" || { fail "$msg"; return 1; }
        step "$msg"
    fi
}

# Boxed menu when whiptail is already installed; colored menu otherwise.
tui_select() {  # tui_select "Title" tag label [tag label ...] → prints the tag
    local title="$1"; shift
    local tags=() labels=()
    while [[ $# -ge 2 ]]; do tags+=("$1"); labels+=("$2"); shift 2; done
    if command -v whiptail >/dev/null 2>&1 && can_prompt; then
        local args=() i=0 out=""
        for tag in "${tags[@]}"; do args+=("$tag" "${labels[$i]}"); i=$((i + 1)); done
        out="$(whiptail --title "$title" --menu "Choose an action" 24 78 12 "${args[@]}" 3>&1 1>&2 2>&3)" && {
            printf '%s' "$out"
            return 0
        }
        return 0
    fi
    line "  ${B}${title}${NC}"; line ""
    local i=0
    for tag in "${tags[@]}"; do
        i=$((i + 1))
        printf '  %b%d%b)  %s\n' "$WH" "$i" "$NC" "${labels[$((i - 1))]}" >&2
    done
    line ""
    local choice; choice="$(ask "Select" "1")"
    [[ "$choice" =~ ^[0-9]+$ ]] || { printf '%s' "${tags[0]}"; return 0; }
    printf '%s' "${tags[$(((choice - 1) % ${#tags[@]}))]}"
}

env_get() {  # env_get FILE KEY → value (empty when missing)
    grep -E "^$2=" "$1" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true
}

env_set() {  # env_set FILE KEY VALUE — rewrite one line, atomically
    local file="$1" key="$2" value="$3" tmp
    tmp="$(mktemp)" || die "Could not stage $file"
    awk -v k="$key" -v v="$value" '
        BEGIN { done = 0 }
        $0 ~ "^" k "=" { if (!done) { print k "=" v; done = 1; next } }
        { print }
        END { if (!done) print k "=" v }
    ' "$file" > "$tmp" || { rm -f "$tmp"; die "Could not update $file"; }
    cat "$tmp" > "$file" || { rm -f "$tmp"; die "Could not update $file"; }
    rm -f "$tmp"
}

# systemd waits up to TimeoutStopSec (90s default) for a stuck service, which
# operators read as a frozen installer. Bound the wait, then force the unit.
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

# Code-tree snapshots for update failover: keep the newest $keep.
snapshot_code() {  # snapshot_code <dir> <label> [keep=2] → prints the file
    local dir="$1" label="$2" keep="${3:-2}"
    [[ -d "$dir" ]] || die "Not installed ($dir missing)"
    mkdir -p /var/backups
    local stamp base file
    stamp="$(date +%Y%m%d-%H%M%S)"
    base="$(basename "$dir")"
    file="/var/backups/${label}-code-${base}-${stamp}.tar.gz"
    tar -czf "$file" -C "$(dirname "$dir")" "$base" 2>/dev/null \
        || die "Could not snapshot $dir"
    step "Snapshot  $file"
    local old
    old="$(ls -t /var/backups/${label}-code-*.tar.gz 2>/dev/null | tail -n +$((keep + 1)) || true)"
    if [[ -n "$old" ]]; then
        # shellcheck disable=SC2086
        rm -f $old
    fi
    printf '%s' "$file"
}

latest_snapshot() {  # latest_snapshot <label> → prints newest code snapshot or empty
    ls -t /var/backups/"$1"-code-*.tar.gz 2>/dev/null | head -1 || true
}

# ── OS / deps ──────────────────────────────────────────────────────────
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
    for cmd in curl tar openssl git python3 sha256sum; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    [[ ${#missing[@]} -eq 0 ]] || pkg_install "${missing[@]}"
    step "System tools present"
}

# Pre-flight: fail BEFORE downloading anything when the box cannot host us.
preflight_install() {
    detect_os
    check_deps
    if [[ -n "$PORT" ]] && port_in_use "$PORT"; then
        die "Port $PORT is already in use — free it or pick another (interactive wizard asks)"
    fi
    if ! has_systemd && [[ "${MODE:-native}" != "docker" ]]; then
        die "systemd not found — native install needs it (use --mode docker)"
    fi
}

# ── Source / env ───────────────────────────────────────────────────────
release_base() { printf '%s-%s' "$APP_SLUG" "$VERSION"; }

release_url() {
    printf 'https://github.com/%s/releases/download/v%s/%s.tar.gz' \
        "$REPO" "$VERSION" "$(release_base)"
}

release_checksum_url() {
    printf 'https://github.com/%s/releases/download/v%s/%s.sha256' \
        "$REPO" "$VERSION" "$(release_base)"
}

# A broken download (redirect stub, proxy block page) must fail here with
# a clear message — never as a checksum mismatch further down.
is_release_archive() { tar -tzf "$1" >/dev/null 2>&1; }

# Download the versioned release file into $1 (an existing directory).
# The tarball holds a repo snapshot plus the prebuilt frontend/dist, so no
# git or npm is needed on the server. The mandatory .sha256 sidecar is
# verified before extraction.
fetch_release() {
    local dest="$1" work base
    base="$(release_base)"
    work="$(mktemp -d)"
    run_step "Downloading release v${VERSION}" \
        curl -fsSL -o "$work/$base.tar.gz" "$(release_url)" \
        || { rm -rf "$work"; die "No verified release file is available for v${VERSION}"; }
    is_release_archive "$work/$base.tar.gz" \
        || { rm -rf "$work"; die "Download for v${VERSION} is not a release archive. Re-bootstrap with the latest installer: bash <(curl -sSL https://raw.githubusercontent.com/${REPO}/main/install.sh)"; }
    curl -fsSL -o "$work/$base.sha256" "$(release_checksum_url)" 2>/dev/null \
        || { rm -rf "$work"; die "Release checksum file is missing for v${VERSION}"; }
    ( cd "$work" && sha256sum -c "$base.sha256" >/dev/null ) \
        || { rm -rf "$work"; die "Release checksum mismatch for v${VERSION}"; }
    step "Checksum ok"
    mkdir -p "$dest"
    tar -xzf "$work/$base.tar.gz" -C "$dest" \
        || { rm -rf "$work"; die "Extract failed"; }
    rm -rf "$work"
    step "Release extracted"
}

write_env() {
    local jwt
    jwt="$(openssl rand -base64 48 2>/dev/null | tr -d '\n')"
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
# The panel owns every file it writes (db, wal, logs) and no other service
# reads them, so the database must be private from its very first byte
# instead of world-readable until 'ovm doctor --fix' notices.
UMask=0077
ExecStart=${UV_BIN} run main.py
# uv exits 143 on SIGTERM: a clean 'ovm stop' must read as inactive,
# not failed, so status and doctor report the truth.
SuccessExitStatus=143
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
    image: ${IMAGE_REPO}:${ACTIVE_IMAGE_VERSION}
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
    info "Pulling published OVManager image…"
    # Compose output goes to stdout — keep the --json contract (exactly one
    # JSON object on stdout) by redirecting operational output to stderr.
    if [[ "$JSON" -eq 1 ]]; then
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" pull && docker compose -f "$COMPOSE_FILE" up -d ) >/dev/stderr \
            || die "docker compose startup failed — docker logs ovmanager"
    else
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" pull && docker compose -f "$COMPOSE_FILE" up -d ) \
            || die "docker compose startup failed — docker logs ovmanager"
    fi
    step "Container  ovmanager"
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

port_in_use() {
    command -v ss >/dev/null 2>&1 || return 1
    ss -ltn 2>/dev/null | awk -v p=":${1}$" '$4 ~ p {exit 0} END {exit 1}'
}

setup_tls() {
    case "$TLS_MODE" in
        le)
            port_in_use 80 && die "Port 80 is busy — Let's Encrypt standalone needs it (or --tls 1 for now)"
            issue_lets_encrypt "$TLS_DOMAIN" "0"
            TLS_KEY="/etc/letsencrypt/$TLS_DOMAIN/privkey.pem"
            TLS_CERT="/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem"
            ;;
        le-ip)
            port_in_use 80 && die "Port 80 is busy — Let's Encrypt standalone needs it (or --tls 1 for now)"
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

# ── Validate / wizard / plan ───────────────────────────────────────────
validate_input() {
    is_port "$PORT" || die "Invalid port: '$PORT'"
    [[ -n "$ADMIN_USER" ]] || ADMIN_USER="$DEFAULT_USER"
    [[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,64}$ ]] || die "Admin username: 3–64 letters, digits, . _ -"
    if [[ -z "$ADMIN_PASS" ]]; then
        ADMIN_PASS="$(rand_pass)"
        GENERATED_PASS=1
        [[ ${#ADMIN_PASS} -ge 8 ]] || die "Could not generate an admin password"
        info "No password given — generated one (shown at the end)"
    fi
    validate_admin_password "$ADMIN_PASS"
    if [[ -n "$PATHPREFIX" ]]; then
        [[ "$PATHPREFIX" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "URL path: letters, digits, dash, underscore"
    fi
    case "$TLS_MODE" in
        le)
            [[ -n "$TLS_DOMAIN" ]] || die "--tls 2 needs --tls-domain DOMAIN" ;;
        le-ip|self|custom) ;;
        none)
            die "Plain HTTP is not allowed — pick TLS: 1 self-signed (default),\n         2 Let's Encrypt domain, 3 Let's Encrypt IP, or 4 custom." ;;
        *) die "Invalid TLS mode: '$TLS_MODE'" ;;
    esac
    if [[ "$TLS_MODE" == "custom" ]]; then
        [[ -f "$TLS_KEY" && -f "$TLS_CERT" ]] || die "Custom TLS files not found"
    fi
}

# Recommended preset: credentials and the private panel path are always
# generated. They can be changed safely after login in the web UI.
panel_express_defaults() {
    EXPRESS=1
    : "${MODE:=native}"
    : "${PORT:=$DEFAULT_PORT}"
    PATHPREFIX="$(rand_path)"
    PATH_SET=1
    ADMIN_USER="$DEFAULT_USER"
    TLS_MODE="self"
    ADMIN_PASS="$(rand_pass)"
    GENERATED_PASS=1
    return 0
}

wizard() {
    if [[ -z "$MODE" ]]; then
        line "${B}Step 1/5 — Install mode${NC}"
        line "  ${WH}1${NC}  Native     systemd service on this host (recommended)"
        line "  ${WH}2${NC}  Docker     containerized, needs Docker Engine"
        local m
        m="$(ask "Mode" "1")"
        case "${m:-1}" in
            2|docker|Docker) MODE="docker" ;;
            *)               MODE="native" ;;
        esac
        line ""
    fi
    line "${B}Step 2/5 — Panel port${NC}"
    line "  ${WH}1${NC}  Default: ${DEFAULT_PORT}"
    line "  ${WH}2${NC}  Custom"
    line "  ${WH}3${NC}  Random (1024-62000)"
    local pc
    pc="$(ask "Port choice" "1")"
    case "${pc:-1}" in
        2) PORT="$(ask "Port" "${PORT:-$DEFAULT_PORT}")" ;;
        3) if command -v shuf >/dev/null 2>&1; then PORT="$(shuf -i 1024-62000 -n 1)"; else PORT="$DEFAULT_PORT"; fi ;;
        *) : "${PORT:=$DEFAULT_PORT}" ;;
    esac
    is_port "$PORT" || die "Invalid port: '$PORT'"
    port_in_use "$PORT" && die "Port $PORT is already in use — free it or pick another"
    line ""
    line "${B}Step 3/5 — Panel URL path${NC}"
    line "  ${GY}A secret path hides the panel from scanners (random is safest).${NC}"
    local path_default="random"
    [[ "$PATH_SET" -eq 1 ]] && path_default="${PATHPREFIX:-root}"
    local path_in
    path_in="$(ask "URL path  (random / root / name)" "$path_default")"
    case "$path_in" in
        root|"/") PATHPREFIX="" ;;
        random|"") PATHPREFIX="$(rand_path)" ;;
        *) PATHPREFIX="${path_in#/}"; PATHPREFIX="${PATHPREFIX%/}" ;;
    esac
    line ""
    line "${B}Step 4/5 — Owner login${NC}"
    ADMIN_USER="$(ask "Admin user" "${ADMIN_USER:-$DEFAULT_USER}")"
    if [[ -z "$ADMIN_PASS" ]]; then
        ADMIN_PASS="$(ask "Admin pass (blank = generate)" "" "h")"
        if [[ -n "$ADMIN_PASS" ]]; then
            prompt_validate_admin_password
        fi
    fi
    if [[ -z "$TLS_MODE" ]]; then
        line ""
        line "${B}Step 5/5 — Certificate (always encrypted)${NC}"
        line "  ${WH}1${NC}  Self-signed (default)      encrypted; one browser warning to click through"
        line "  ${WH}2${NC}  Let's Encrypt (domain)     needs a domain pointed here + free port 80"
        line "  ${WH}3${NC}  Let's Encrypt (this IP)    short-lived cert, no domain needed"
        line "  ${WH}4${NC}  Custom key + cert          bring your own PEM files"
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

# Plan card: printed before every mutating action (no --dry-run flag —
# the plan is always shown).
print_plan() {
    hr
    kv "OS"      "$OS_NAME"
    kv "Version" "v${VERSION} (verified release)"
    kv "Mode"    "${B}${MODE}${NC}"
    kv "Port"    "$PORT"
    kv "URL path" "$( [[ -n "$PATHPREFIX" ]] && printf '/%s/' "$PATHPREFIX" || printf '/' )"
    kv "Admin"   "$ADMIN_USER"
    kv "TLS"     "$TLS_MODE"
    kv "Install" "$INSTALL_DIR"
    kv "Data"    "$DATA_DIR"
    hr
}

emit_json() {
    local ok="$1" url
    url="$(panel_url)"
    python3 - "$ok" "$MODE" "$url" "$ADMIN_USER" "$ADMIN_PASS" "$INSTALL_DIR" "$DATA_DIR" "$TLS_MODE" "$PORT" "$PATHPREFIX" "$GENERATED_PASS" "$VERSION" <<'PY'
import json, sys
(ok, mode, url, user, password, install, data, tls, port,
 path, gen, version) = sys.argv[1:]
out = {
    "ok": ok == "1",
    "version": version,
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
    line "  ${GR}Ready — save this login${NC}"
    hr
    kv "Open"   "${WH}${url}${NC}"
    kv "Login"  "${GR}${ADMIN_USER}${NC}"
    if [[ "$GENERATED_PASS" -eq 1 ]]; then
        kv "Password" "${YL}${ADMIN_PASS}${NC}  ${GY}(generated — save this)${NC}"
    else
        kv "Password" "${GY}(the one you set)${NC}"
    fi
    kv "Manage" "ovm  (status, logs, backup, TLS, recovery)"
    kv "Logs"   "$logs"
    kv "Data"   "$DATA_DIR"
    line ""
    info "Next: install an OVNode (one per VPN server), then Nodes → Add Node in the panel."
    info "Docs: https://github.com/anonysec/OVManager#readme"
    line ""
}

# ── Actions ────────────────────────────────────────────────────────────
do_install() {
    [[ -d "$INSTALL_DIR" ]] && die "Already installed ($INSTALL_DIR). Use: $0 update"
    mkdir -p "$DATA_DIR"
    # Native panel state holds secrets — private from birth (Docker data
    # belongs to uid 1000 instead; doctor --fix normalizes old installs).
    [[ "$MODE" == "docker" ]] || chmod 700 "$DATA_DIR"
    print_plan
    hr; info "Step 1/4 — Download verified release v${VERSION}"
    fetch_release "$INSTALL_DIR"

    info "Step 2/4 — Certificate and configuration"
    setup_tls
    write_env

    local scheme; scheme="$(scheme_of)"

    info "Step 3/4 — Runtime and service"
    if [[ "$MODE" == "docker" ]]; then
        compose_up
    else
        ensure_uv
        cd "$INSTALL_DIR"
        run_step "Python packages" "$UV_BIN" sync --frozen --no-dev --quiet
        [[ -d "$INSTALL_DIR/frontend/dist" ]] || die "Verified release is missing the prebuilt frontend"
        step "Frontend prebuilt"
        write_systemd_unit
        run_step "Service started" systemctl_bounded restart
    fi

    info "Step 4/4 — Health check and finish"
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 40 \
        || warn "No answer on /health yet — check logs"
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
    if [[ "$JSON" -eq 1 ]]; then emit_json 1; fi
}

do_update() {
    operation_begin update
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    info "Updating OVManager to v${VERSION}…"
    [[ -f "$COMPOSE_FILE" ]] && MODE="docker"
    read_env_port
    : "${PORT:=$DEFAULT_PORT}"
    : "${TLS_MODE:=none}"
    if [[ "$MODE" == "docker" ]]; then ensure_docker; else ensure_uv; fi

    local from_version safety snapshot scheme activated=0
    from_version="$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$INSTALL_DIR/backend/version.py" 2>/dev/null | head -1)"
    : "${from_version:=unknown}"
    scheme="$(scheme_of)"
    print_plan
    update_state preflight "$from_version" "$VERSION"

    info "Step 1/6 — Verified safety backup"
    safety="$(update_safety_backup "$from_version")" || die "Could not create the mandatory pre-update backup"
    [[ -n "$safety" && -f "$safety" ]] || die "The pre-update backup was not created"
    snapshot="$(snapshot_code "$INSTALL_DIR" "panel" 2)"
    update_state staging "$from_version" "$VERSION" "$safety"

    info "Step 2/6 — Stage verified release"
    rm -rf "$UPDATE_STAGE"
    mkdir -p "$UPDATE_STAGE"
    fetch_release "$UPDATE_STAGE"
    cp -p "$INSTALL_DIR/.env" "$UPDATE_STAGE/.env" || die "Could not preserve configuration"
    chmod 600 "$UPDATE_STAGE/.env"
    # Retired secrets must not reach the candidate: the new backend rejects
    # unknown .env keys and would crash-loop on first boot.
    sed -i '/^BACKUP_ENCRYPT_KEY=/d' "$UPDATE_STAGE/.env"
    if [[ "$MODE" != "docker" ]]; then
        ( cd "$UPDATE_STAGE" && run_step "Staged Python packages" "$UV_BIN" sync --frozen --no-dev --quiet ) \
            || die "Could not prepare the staged release; current version is still running"
        [[ -d "$UPDATE_STAGE/frontend/dist" ]] || die "Verified release is missing the prebuilt frontend"
    fi

    info "Step 3/6 — Enter maintenance mode"
    : > "$UPDATE_MARKER"
    chmod 600 "$UPDATE_MARKER"
    update_state activating "$from_version" "$VERSION" "$safety"
    if [[ "$MODE" == "docker" ]]; then
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" down ) >/dev/null 2>&1 || true
    else
        systemctl_bounded stop
    fi

    info "Step 4/6 — Activate candidate"
    rm -rf "$UPDATE_PREVIOUS"
    if mv "$INSTALL_DIR" "$UPDATE_PREVIOUS" && mv "$UPDATE_STAGE" "$INSTALL_DIR"; then
        activated=1
    else
        # If the first rename never happened, the active release is untouched.
        # If it did, restore it before clearing maintenance mode. A failed
        # restore deliberately leaves the marker in place to block writes.
        if [[ -d "$INSTALL_DIR" ]] || { [[ -d "$UPDATE_PREVIOUS" ]] && mv "$UPDATE_PREVIOUS" "$INSTALL_DIR"; }; then
            rm -f "$UPDATE_MARKER"
            update_state failed_over "$from_version" "$VERSION" "$safety"
            die "Could not activate the staged release; the previous release remains active and data was not changed"
        fi
        update_state recovery_required "$from_version" "$VERSION" "$safety"
        die "Could not activate or restore release files. Writes remain blocked; run: ovm recover-update"
    fi

    local start_ok=0
    if [[ "$MODE" == "docker" ]]; then
        ( compose_up ) && start_ok=1 || true
    else
        run_step "Candidate service started" systemctl_bounded restart && start_ok=1 || true
    fi

    info "Step 5/6 — Verify candidate"
    update_state verifying "$from_version" "$VERSION" "$safety"
    if [[ "$start_ok" -eq 1 ]] && wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
        local reported
        reported="$(candidate_version)"
        [[ "$reported" == "$VERSION" ]] || { warn "Candidate reported version '${reported:-unknown}', expected '$VERSION'"; start_ok=0; }
    else
        start_ok=0
    fi

    if [[ "$start_ok" -ne 1 ]]; then
        fail "Candidate verification failed — failing over to v${from_version}"
        update_state failing_over "$from_version" "$VERSION" "$safety"
        if [[ "$MODE" == "docker" ]]; then
            ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" down ) >/dev/null 2>&1 || true
        else
            systemctl_bounded stop >/dev/null 2>&1 || true
        fi
        rm -rf "$UPDATE_STAGE"
        mv "$INSTALL_DIR" "$UPDATE_STAGE" || true
        mv "$UPDATE_PREVIOUS" "$INSTALL_DIR" \
            || { update_state recovery_required "$from_version" "$VERSION" "$safety"; die "Automatic failover could not restore the previous release. Snapshot: $snapshot"; }
        local db_restored=0
        if db_restore_needed "$safety"; then
            restore_update_database "$safety" \
                || { update_state recovery_required "$from_version" "$VERSION" "$safety"; die "Previous code was restored but the database safety backup could not be restored"; }
            db_restored=1
        else
            step "Database untouched by the candidate — restore skipped"
        fi

        local rollback_started=0
        if [[ "$MODE" == "docker" ]]; then
            ACTIVE_IMAGE_VERSION="$from_version"
            ( compose_up ) && rollback_started=1 || true
        else
            run_step "Previous service restarted" systemctl_bounded restart && rollback_started=1 || true
        fi
        if [[ "$rollback_started" -eq 1 ]] && wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
            rm -f "$UPDATE_MARKER"
            update_state failed_over "$from_version" "$VERSION" "$safety"
            if [[ "$db_restored" -eq 1 ]]; then
                die "Update failed over safely to v${from_version}. Data was restored from $safety. Check logs before retrying."
            else
                die "Update failed over safely to v${from_version} (database was untouched — no restore needed). Check logs before retrying."
            fi
        fi
        update_state recovery_required "$from_version" "$VERSION" "$safety"
        die "Update recovery needs attention. Previous files: $INSTALL_DIR; safety backup: $safety; snapshot: $snapshot"
    fi

    info "Step 6/6 — Commit update"
    install_cli
    rm -f "$UPDATE_MARKER"
    # Verification mode intentionally paused all background writers. Restart
    # once without the marker so normal scheduling resumes, then require one
    # final healthy response before committing the journal.
    if [[ "$MODE" == "docker" ]]; then
        docker restart ovmanager >/dev/null 2>&1 || true
    else
        systemctl_bounded restart >/dev/null 2>&1 || true
    fi
    if ! wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
        : > "$UPDATE_MARKER"; chmod 600 "$UPDATE_MARKER"
        update_state recovery_required "$from_version" "$VERSION" "$safety"
        die "Candidate passed verification but failed its final restart. Writes are blocked; run: ovm recover-update"
    fi
    update_state committed "$from_version" "$VERSION" "$safety"
    step "Update complete  v${from_version} → v${VERSION}"
    step "Failover release kept at $UPDATE_PREVIOUS"
    line ""
    if [[ "$JSON" -eq 1 ]]; then emit_json 1; fi
    return 0
}

do_recover_update() {
    if [[ ! -f "$UPDATE_STATE" ]]; then
        [[ -f "$UPDATE_MARKER" ]] && die "Update maintenance marker exists but its state journal is missing"
        step "No interrupted update needs recovery"
        return 0
    fi
    local phase from target safety scheme reported
    read -r phase from target safety < <(python3 - "$UPDATE_STATE" <<'PY'
import json, sys
x=json.load(open(sys.argv[1]))
print(x.get("phase","unknown"), x.get("from_version","unknown"), x.get("to_version","unknown"), x.get("safety_backup") or "")
PY
) || die "Update state journal is unreadable"
    case "$phase" in
        committed|failed_over)
            if [[ ! -f "$UPDATE_MARKER" ]]; then
                step "No interrupted update needs recovery"
                return 0
            fi
            ;;
        preflight|staging)
            # Activation had not begun, so the installed release and database
            # are untouched. Stale staging content can be discarded safely.
            check_root
            rm -rf "$UPDATE_STAGE"
            rm -f "$UPDATE_MARKER"
            update_state failed_over "$from" "$target" "$safety"
            step "Cleared an interrupted pre-activation update; v${from} remains active"
            return 0
            ;;
        activating|verifying|failing_over|recovery_required) ;;
        *) die "Update journal has unknown phase '$phase'; writes remain blocked" ;;
    esac
    check_root
    if [[ ! -f "$UPDATE_MARKER" ]]; then
        : > "$UPDATE_MARKER"
        chmod 600 "$UPDATE_MARKER"
        warn "Re-created the missing update maintenance marker"
    fi
    [[ -f "$COMPOSE_FILE" ]] && MODE="docker" || MODE="native"
    read_env_port; : "${PORT:=$DEFAULT_PORT}"; : "${TLS_MODE:=none}"
    scheme="$(scheme_of)"
    reported="$(candidate_version)"
    if [[ -n "$reported" && "$reported" == "$target" ]]; then
        rm -f "$UPDATE_MARKER"
        update_state committed "$from" "$target" "$safety"
        step "Recovered update journal — v${target} is healthy"
        return 0
    fi
    if [[ -n "$reported" && "$reported" == "$from" && ! -d "$UPDATE_PREVIOUS" ]]; then
        rm -f "$UPDATE_MARKER"
        update_state failed_over "$from" "$target" "$safety"
        step "Recovered update journal — previous v${from} is healthy"
        return 0
    fi
    [[ -d "$UPDATE_PREVIOUS" ]] || {
        # Activation never swapped the trees (killed before/during the
        # rename): the installed release IS the pre-update one, so discard
        # staging and (re)start it. The database was never touched.
        rm -rf "$UPDATE_STAGE"
        if [[ "$MODE" == "docker" ]]; then
            ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" up -d ) >/dev/null 2>&1 || true
        else
            systemctl_bounded restart >/dev/null 2>&1 || systemctl start "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
        fi
        if wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
            rm -f "$UPDATE_MARKER"
            update_state failed_over "$from" "$target" "$safety"
            step "Interrupted update never activated — v${from} restarted, staging discarded"
            return 0
        fi
        update_state recovery_required "$from" "$target" "$safety"
        die "Interrupted update never activated and v${from} does not answer health. Run: ovm logs 100"
    }
    info "Interrupted candidate is unhealthy — failing over to v${from}"
    if [[ "$MODE" == "docker" ]]; then
        docker rm -f ovmanager >/dev/null 2>&1 || true
    else
        systemctl_bounded stop >/dev/null 2>&1 || true
    fi
    rm -rf "$UPDATE_STAGE"
    [[ -d "$INSTALL_DIR" ]] && mv "$INSTALL_DIR" "$UPDATE_STAGE"
    mv "$UPDATE_PREVIOUS" "$INSTALL_DIR" || die "Could not restore the previous release directory"
    [[ -n "$safety" ]] && restore_update_database "$safety" \
        || die "Previous release restored, but the database safety backup could not be restored"
    if [[ "$MODE" == "docker" ]]; then
        ACTIVE_IMAGE_VERSION="$from"
        compose_up
    else
        systemctl_bounded restart
    fi
    if wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
        rm -f "$UPDATE_MARKER"
        update_state failed_over "$from" "$target" "$safety"
        step "Interrupted update failed over safely to v${from}"
        return 0
    fi
    update_state recovery_required "$from" "$target" "$safety"
    die "Previous release was restored but is not healthy. Run: ovm logs 100"
}


do_uninstall() {
    operation_begin uninstall
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    check_root
    hr
    kv "Remove" "$INSTALL_DIR"
    kv "Data"   "$DATA_DIR $( [[ "$PURGE" -eq 1 ]] && printf '(will be deleted)' || printf '(kept)' )"
    hr
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
    info "Manage the panel with: ovm  (status, logs, backup, TLS, recovery)"
    if ! can_prompt; then
        fail "Already installed. Re-run with:  $0 update"
        exit 2
    fi
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

start_menu() {
    line "  ${B}OVManager Setup${NC}"
    hr
    line ""
    line "  ${GR}1.${NC} Install              ${GY}Recommended${NC}"
    line "  ${WH}2.${NC} Install with Docker"
    line ""
    line "  ${WH}0.${NC} Exit"
    line ""
    local choice
    choice="$(ask "Select" "1")"
    case "${choice:-1}" in
        1) MODE="native"; panel_express_defaults ;;
        2) MODE="docker"; panel_express_defaults ;;
        0) line "Cancelled. No changes were made."; exit 0 ;;
        *) warn "Choose 0, 1, or 2."; start_menu ;;
    esac
    line ""
}

# The manager (manager.sh) is installed as "ovmanager" (+ "ovm" alias), so
# day-to-day ops live outside this installer. Refreshed on every update,
# which auto-swaps boxes whose ovm is an old installer copy.
install_cli() {
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

# ── Help / args / main ─────────────────────────────────────────────────
usage() {
    cat <<EOF
OVManager Setup v${VERSION}

USAGE
  Interactive:
    bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)

  Unattended Install:
    curl -sSL URL | sudo bash -s -- --yes --json

  Unattended Install with Docker:
    curl -sSL URL | sudo bash -s -- --docker --yes --json

COMMANDS
  update [-v VERSION]       Staged update with backup and automatic failover
  recover-update            Recover an update interrupted by reboot/power loss
  uninstall [--purge]       Remove the app; keep data unless --purge
  help                      Show this help

OPTIONS
  --docker                  Install with Docker
  -v, --version VERSION     Install/update a specific release
  -y, --yes                 Never prompt
  -j, --json                Machine-readable result on stdout
  --purge                   Uninstall: also delete data and certificates
  -h, --help                Show this help

Fresh installs generate the owner password and private panel URL. Save the
Ready card; both values can be changed later in the web UI.

After installation, use ovm (alias: ovmanager) for status, service controls,
logs, backups, HTTPS, diagnostics, recovery, updates, and uninstall.

EXIT
  0 ok   1 error   2 already installed/cancelled   130 interrupted
EOF
    exit 0
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        CLI_GIVEN=1
        case "$1" in
            -p|--pass)    [[ $# -ge 2 ]] || die "-p needs a password"; ADMIN_PASS="$2"; shift 2 ;;
            --docker)      MODE="docker"; shift ;;
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
            -v|--version)  [[ $# -ge 2 ]] || die "--version needs vX.Y.Z"; PIN="$2"; shift 2 ;;
            -y|--yes) YES=1; shift ;;
            -j|--json) JSON=1; shift ;;
            --purge)       PURGE=1; shift ;;
            -i)            ACTION="interactive"; shift ;;
            -h|--help)     usage ;;
            help)          usage ;;
            update)        ACTION="update"; shift ;;
            recover-update) ACTION="recover-update"; shift ;;
            uninstall)     ACTION="uninstall"; shift ;;
            interactive)   ACTION="interactive"; shift ;;
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
    [[ -z "$ADMIN_PASS" && -n "${OVM_PASS:-}" ]] && ADMIN_PASS="$OVM_PASS"
    [[ -z "$TLS_MODE" && -n "${OVM_TLS:-}" ]] && TLS_MODE="$OVM_TLS"
    [[ -z "$TLS_DOMAIN" && -n "${OVM_TLS_DOMAIN:-}" ]] && TLS_DOMAIN="$OVM_TLS_DOMAIN"
    [[ -z "$PUBLIC_URL" && -n "${OVM_PUBLIC_URL:-}" ]] && PUBLIC_URL="$OVM_PUBLIC_URL"
    # Explicit success: the trailing && lines above return 1 when their
    # tests are false, which would trip `set -e` on return.
    return 0
}

main() {
    parse_args "$@"
    apply_env
    if [[ -n "$PIN" ]]; then
        [[ "$PIN" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Bad --version '$PIN' (use vX.Y.Z)"
        VERSION="${PIN#v}"
    fi
    if [[ "$JSON" -eq 1 ]]; then YES=1; fi
    if can_prompt && [[ "$JSON" -eq 0 ]]; then
        command clear >/dev/null 2>&1 || true
    fi
    banner

    # Root is required only for paths that change the system. Dry plan
    # output and the already-installed guard must work for anyone,
    # including CI sandboxes and non-root operators.
    case "$ACTION" in
        uninstall) check_root; do_uninstall; exit 0 ;;
        recover-update) do_recover_update; exit 0 ;;
        update)
            detect_os
            check_deps
            check_root
            [[ "$YES" -eq 1 ]] || confirm "Update OVManager to v${VERSION} now?" || exit 0
            do_update
            exit 0
            ;;
        interactive)
            [[ -d "$INSTALL_DIR" ]] && die "Already installed ($INSTALL_DIR). Use: $0 update"
            check_root
            detect_os
            check_deps
            EXPRESS=0
            run_wizard_install
            exit 0
            ;;
    esac

    if [[ -d "$INSTALL_DIR" ]]; then
        already_installed_menu
        exit 0
    fi
    if [[ "$CLI_GIVEN" -eq 0 && "$YES" -eq 0 ]] && ! can_prompt; then
        die "No interactive terminal. Use --yes to Install or --docker --yes to Install with Docker."
    fi
    check_root

    detect_os
    check_deps

    # Bare interactive run → Express/Custom choice. Scripts/flags and
    # OVM_* env configuration keep the machine path untouched.
    if [[ "$CLI_GIVEN" -eq 0 ]] && can_prompt; then
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
        if [[ -z "$ADMIN_PASS" ]]; then
            ADMIN_PASS="$(rand_pass)"
            GENERATED_PASS=1
        fi
    fi

    validate_input
    do_install
}

run_wizard_install() {
    EXPRESS=0
    wizard
    validate_input
    do_install
}

# Banner: the tagline advertises a fresh install, so it must not appear on
# update/uninstall/repair where it reads as if work were about to start.
banner() {
    local subtitle
    case "$ACTION" in
        install) subtitle="Secure VPN panel — up and running in a few minutes" ;;
        *)      subtitle="Secure VPN panel" ;;
    esac
    line ""
    line "  ${B}OVManager installer${NC}  ${GY}v${VERSION}${NC}"
    line "  ${GY}${subtitle}${NC}"
    line ""
}

main "$@"
