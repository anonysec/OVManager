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
#   curl -sSL URL | sudo bash -s -- --docker --yes
#
# No owner password is set here: the install prints a one-time claim key and
# the operator claims the panel in the browser (ovm owner-claim reprints one).
#
# Day-to-day operations (status, logs, backup, restore, TLS, recovery) live in the
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
VERSION="1.0.0"
IMAGE_REPO="ghcr.io/${REPO,,}"
ACTIVE_IMAGE_VERSION="$VERSION"
# Terminal command installed by install_cli() (copy of the manager).
BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"

# The account the panel itself runs as, on a native install.
#
# The panel is an HTTPS server that parses untrusted input from anyone who can
# reach the port, so running it as root meant a remote compromise of the web
# app was a compromise of the box. It needs almost nothing: read its own code,
# read .env, write its data directory, read the TLS key, and make node RPCs.
# A dedicated unprivileged account covers all of that, and mirrors what the
# Docker image already does with its own appuser.
#
# It cannot update itself: `ovm update` replaces the tree and restarts the
# unit, which needs root. The in-app update button says so and prints the
# command instead — the same shape Docker already takes.
PANEL_USER="${OVM_PANEL_USER:-ovmanager}"
CLI_NAME="ovmanager"
CLI_ALIAS="ovm"

# ── Shared helpers (scripts/lib) ───────────────────────────────────────
# The helpers are not copied into this file: they are fetched and sourced
# here, so scripts/lib is their one definition (colour, output, prompts, env,
# system, backups, TLS, policy). Sourced before anything else uses them.
#
# At the installer's OWN VERSION, never the --version target: the libs are
# installer infrastructure, so `install.sh -v 1.0.15` fetches this installer's
# libs and pins only the app tarball. Pinning them to the target would break
# installing anything older than the split — those tags carry no libs at all.
#
# All-or-nothing into a staging dir: a partial set is never sourced, because a
# half-defined environment then fails twenty lines later as something else.
LIB_BASE="${OVM_LIB_BASE:-https://raw.githubusercontent.com/${REPO}/v${VERSION}/scripts/lib}"
LIB_FILES="common prompt env system backup tls policy"

_boot_die() {  # die() lives in the libs, which are exactly what may be missing
    # Plain text: the colour globals arrive with the libs, and an installer
    # that cannot load them is usually piping its output anyway.
    printf '\n  Error: %s\n  Run ID: %s\n\n' "$1" "${OVM_RUN_ID:-$(date +%Y%m%d-%H%M%S)-$$}" >&2
    exit 1
}

_libs_source() {  # <dir> → source the set, or nothing when one file is missing
    local dir="$1" name
    for name in $LIB_FILES; do
        [[ -s "$dir/$name.sh" ]] || return 1
    done
    for name in $LIB_FILES; do
        # shellcheck disable=SC1090
        . "$dir/$name.sh"
    done
}

# An installed tree, and a checkout, already have the libs beside the script.
# A curl-piped installer is a lone file in /dev/fd or /tmp, so it fetches its
# own — the same set the matching release tag carries.
_libs_install() {
    local here="" stage name
    if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
        here="$(dirname -- "${BASH_SOURCE[0]}")"
    fi
    if [[ -n "$here" ]] && _libs_source "$here/scripts/lib"; then
        return 0
    fi
    stage="$(mktemp -d)" || _boot_die "Could not create a staging directory for scripts/lib"
    for name in $LIB_FILES; do
        curl -fsSL --max-time 60 -o "$stage/$name.sh" "$LIB_BASE/$name.sh" \
            || _boot_die "Could not fetch ${LIB_BASE}/${name}.sh — this installer cannot run without its libraries"
    done
    _libs_source "$stage" || _boot_die "The set fetched from $LIB_BASE is incomplete"
    # The functions are loaded; the files are not read again.
    rm -rf "$stage"
}
_libs_install

# Pinpoint trap: any future failure (real or environmental) reports the exact
# command and line instead of surfacing as a mystery message elsewhere.
trap 'warn "Command failed near line $LINENO (running: ${BASH_COMMAND:0:80})"' ERR

# ── Flags (defaults) ───────────────────────────────────────────────────
# Three flags: -y/--yes, --docker, -h/--help. Everything else that used to be
# a flag is an OVM_* environment variable (see apply_env) — the values that
# shape what gets written stay install-time, the rest move to `ovm`.
PORT="" PATHPREFIX="" ADMIN_USER=""
TLS_MODE="" TLS_DOMAIN="" TLS_KEY="" TLS_CERT=""
PUBLIC_URL="" MODE="" ACTION="install" PIN=""
YES=0 PURGE=0 DRY=0 PATH_SET=0
CLI_GIVEN=0 EXPRESS=0 CLAIM_KEY=""
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

# The owner account is not created here, and no password is minted: the
# operator claims the panel in the browser with a one-time key. A key can be
# reprinted at will (ovm owner-claim) because it is not the credential, and
# there is nothing in scrollback or in a file that a stolen copy could use
# twice. mint_claim_key lives in scripts/lib/policy.sh.
issue_claim_key() {
    CLAIM_KEY="$(mint_claim_key)" || warn "Could not write the claim key — run: ovm owner-claim"
    return 0
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

# A release version: MAJOR.MINOR.PATCH, optionally with a pre-release or build
# suffix (1.2.3-rc1, 1.2.3+build5), and an optional leading v. The suffix is
# what lets a pre-release be installed by name, and the tag it resolves to is
# "v" + this (see release_url), so both spellings of the same release work.
valid_release_version() {
    [[ "$1" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]
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
UV_INSTALL_VERSION="0.12.19"

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        UV_BIN="$(command -v uv)"; step "uv  $UV_BIN"; return
    fi
    info "Installing uv…"
    # Trusted sources first (distro package, then the pinned release on the
    # index), then the upstream script.
    pkg_install uv >/dev/null 2>&1 \
        || python3 -m pip install --quiet "uv==${UV_INSTALL_VERSION}" >/dev/null 2>&1 \
        || python3 -m pip install --quiet uv >/dev/null 2>&1 \
        || fetch_and_run_installer "https://astral.sh/uv/${UV_INSTALL_VERSION}/install.sh" "#!/bin/sh" "uv-install" \
        || die "Could not install uv. Manual: python3 -m pip install uv  (or https://docs.astral.sh/uv/)"
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
    if [[ -n "$PORT" ]]; then
        port_available_or_die "$PORT" "interactive wizard asks"
    fi
    if ! has_systemd && [[ "${MODE:-native}" != "docker" ]]; then
        die "systemd not found — native install needs it (use --mode docker)"
    fi
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
    # --no-same-owner: an archive from an older release still carries whatever
    # uid built it, and extracting as root would restore that. The install runs
    # as root, so honouring the archive's numeric ids is exactly backwards.
    tar --no-same-owner -xzf "$work/$base.tar.gz" -C "$dest" \
        || { rm -rf "$work"; die "Extract failed"; }
    # Root-owned explicitly, so the tree does not depend on how it was built.
    # The root requirement below depends on this: a tree this user cannot
    # traverse is what keeps a non-root operator out of the panel's secrets.
    chown -R root:root "$dest"
    rm -rf "$work"
    step "Release extracted"
}

ensure_panel_user() {  # create the service account if it is not there yet
    [[ "$MODE" == "docker" ]] && return 0   # the image has its own appuser
    if ! id -u "$PANEL_USER" >/dev/null 2>&1; then
        useradd --system --no-create-home --home-dir "$DATA_DIR" \
            --shell /usr/sbin/nologin --comment "OVManager panel service account" "$PANEL_USER" \
            || die "Could not create the $PANEL_USER service account"
        step "Service account $PANEL_USER created"
    fi
}

# Give the service account exactly what it needs, and no more.
#
#   .env      0640 root:$PANEL_USER  group-read, so no local account but the
#                                   service one can see the admin hash, the
#                                   JWT key or the secret URL path
#   tree      0750 root:$PANEL_USER  readable and traversable by the service
#                                   account, invisible to everyone else
#   data dir  0700 $PANEL_USER       the panel writes the database; it is the
#                                   owner's job and nobody else's business
#   TLS key   0640 root:$PANEL_USER  same reasoning as .env
grant_panel_access() {
    [[ "$MODE" == "docker" ]] && return 0
    chgrp "$PANEL_USER" "$INSTALL_DIR/.env" 2>/dev/null || true
    chmod 640 "$INSTALL_DIR/.env"
    chown root:"$PANEL_USER" "$INSTALL_DIR"
    chmod 750 "$INSTALL_DIR"
    [[ -n "$TLS_KEY" && -f "$TLS_KEY" ]] && { chgrp "$PANEL_USER" "$TLS_KEY" 2>/dev/null || true; chmod 640 "$TLS_KEY"; }
    # The venv is interpreter, not state: the panel user needs to read and
    # execute it, nothing more. Installs made while the umask leaked have it
    # 0700 root:root, which the service cannot even traverse.
    if [[ -d "$INSTALL_DIR/.venv" ]]; then
        chgrp -R "$PANEL_USER" "$INSTALL_DIR/.venv" 2>/dev/null || true
        chmod -R g+rX,o-rwx "$INSTALL_DIR/.venv" 2>/dev/null || true
    fi
    chown -R "$PANEL_USER":"$PANEL_USER" "$DATA_DIR"
    chmod 700 "$DATA_DIR"
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
    # Scoped to this write. Unscoped, it leaked into everything the installer
    # did afterwards: `uv sync` then created .venv 0700 root:root, the panel
    # user could not traverse into it, and the service died with
    # status=203/EXEC on every fresh native install.
    (
    umask 077
    {
        printf 'HOST=0.0.0.0\n'
        printf 'PORT=%s\n' "$PORT"
        printf 'URLPATH=%s\n' "$PATHPREFIX"
        printf 'ADMIN_USERNAME=%s\n' "$ADMIN_USER"
        # No credential here, ever: the owner is a row in the panel database
        # (schema v16). The install prints a one-time claim key instead, and
        # the browser turns that into the bcrypt row. ADMIN_PASSWORD in .env
        # is ignored by the panel.
        printf 'JWT_SECRET_KEY=%s\n' "$jwt"
        printf 'DATA_DIR=%s\n' "$data_dir"
        [[ -n "$PUBLIC_URL" ]] && printf 'PUBLIC_URL=%s\n' "$PUBLIC_URL"
        [[ -n "$TLS_KEY" ]] && printf 'SSL_KEYFILE=%s\n' "$TLS_KEY"
        [[ -n "$TLS_CERT" ]] && printf 'SSL_CERTFILE=%s\n' "$TLS_CERT"
    } > "$INSTALL_DIR/.env"
    )
    # Ownership is applied later, in share_env_with_container, once the image
    # is on the box and its gid can be read rather than guessed.
    [[ "$MODE" == "docker" ]] || chmod 600 "$INSTALL_DIR/.env"
    step "Config  $INSTALL_DIR/.env"
}

# The container reads the .env through a read-only bind mount, not through
# compose `env_file`: compose expands $NAME inside env_file values, which
# truncates a bcrypt hash at its salt (measured over 400 hashes: 83% start with
# a letter or dot, i.e. a valid variable name). So the file must be readable by
# the app user's group and by nobody else — 0600 root puts the panel's own
# config out of reach, and chowning to uid 1000 would hand the admin hash and
# the JWT secret to the first human user on the host.
#
# The gid is read from the image, so there is no constant to keep in step with
# the Dockerfile and no assumption about which gids this host already uses.
share_env_with_container() {
    local envfile="$INSTALL_DIR/.env" gid
    # `id -g ovpanel` would look up a *user* by that name; the group is in
    # /etc/group, which getent reads. The awk fallback needs no libc tools.
    gid="$(docker run --rm --entrypoint getent "${IMAGE_REPO}:${ACTIVE_IMAGE_VERSION}" group ovpanel 2>/dev/null | cut -d: -f3 | tr -d '[:space:]')"
    [[ "$gid" =~ ^[0-9]+$ ]] || gid="$(docker run --rm --entrypoint /bin/sh "${IMAGE_REPO}:${ACTIVE_IMAGE_VERSION}" -c "awk -F: '\$3 == \"ovpanel\" {print \$3}' /etc/group" 2>/dev/null | tr -d '[:space:]')"
    [[ "$gid" =~ ^[0-9]+$ ]] && [[ "$gid" != "0" ]] \
        || die "Could not read the ovpanel gid from ${IMAGE_REPO}:${ACTIVE_IMAGE_VERSION}. The panel config must be readable by that group, so this cannot be guessed — check 'docker run --rm --entrypoint getent $IMAGE_REPO:$ACTIVE_IMAGE_VERSION group ovpanel'."
    # Group-sharing the config only widens access to a group that has no
    # members. If the image's gid already belongs to a populated group on this
    # host, the admin hash and the JWT secret would become readable by those
    # members — refuse rather than quietly widen.
    local existing members
    existing="$(getent group "$gid" 2>/dev/null | cut -d: -f1)"
    members="$(getent group "$gid" 2>/dev/null | cut -d: -f4)"
    if [[ -n "$members" ]]; then
        die "GID $gid belongs to group '$existing' on this host and it has members ($members). Sharing the panel config by that group would expose the secret panel URL path to them. Rebuild the image with a different gid for ovpanel, or remove those members."
    fi
    [[ -n "$existing" ]] || groupadd -g "$gid" ovpanel 2>/dev/null || true
    chown "root:$gid" "$envfile"
    chmod 640 "$envfile"
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
# Not root: the panel is a network-facing service, and a compromise of it
# should not be a compromise of the host. It reads its code and .env through
# the $PANEL_USER group, owns its data directory, and cannot update itself.
User=${PANEL_USER}
Group=${PANEL_USER}
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="DATA_DIR=${DATA_DIR}"
# The panel owns every file it writes (db, wal, logs) and no other service
# reads them, so the database must be private from its very first byte
# instead of world-readable until 'ovm doctor --fix' notices.
UMask=0077
# The venv's own interpreter, not \`uv run\`: \`uv run\` re-resolves and
# rebuilds the project before starting it, writing egg-info and the lock into
# the tree, which an unprivileged service account cannot do. The venv python
# needs no write access and is what uv ends up executing anyway.
ExecStart=${INSTALL_DIR}/.venv/bin/python3 main.py
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
    # No env_file: compose expands \$NAME inside env_file values, which
    # truncates ADMIN_PASSWORD_HASH at its salt and any password containing
    # a dollar sign. The panel reads the same file from disk instead
    # (pydantic-settings resolves it to /app/.env), so there is one source
    # of truth. The \$ is escaped because this heredoc is unquoted.
    volumes:
      - ${DATA_DIR}:/app/data
      - ${INSTALL_DIR}/.env:/app/.env:ro
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
    ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" pull ) \
        || die "docker compose pull failed — is the image published?"
    # The image is here now, so the config can be shared with the container by
    # the very gid the image defines — no constant to keep in step with the
    # Dockerfile, and no guess about which gids the host already uses.
    share_env_with_container
    ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" up -d ) \
        || die "docker compose startup failed — docker logs ovmanager"
    step "Container  ovmanager"
}

# The panel binds this port on the host in both modes, so one check serves
# both. Shared rather than written twice: the wizard wants it at prompt time
# (before three more questions) and validate_input needs it on the
# non-interactive path, and two copies of the same test would drift.
port_available_or_die() {  # port_available_or_die <port> [hint]
    # `if`, not `port_in_use ... && die`: a && list returns 1 when the port is
    # free, so as a plain statement under `set -e` that aborted every
    # non-interactive install. A condition is also exempt from the ERR trap,
    # which otherwise warned on every free port.
    if port_in_use "$1"; then
        die "Port $1 is already in use — free it or pick another${2:+ ($2)}"
    fi
    return 0
}

# ── Validate / wizard / plan ───────────────────────────────────────────
validate_input() {
    is_port "$PORT" || die "Invalid port: '$PORT'"
    # A non-interactive install defaults PORT *after* preflight_install has
    # already run, so preflight's check never saw it. Without this, a busy port
    # on `curl ... | bash -s -- --docker --yes` — the documented one-liner —
    # failed much later with a raw Docker daemon error about address
    # already in use, after the download and the compose file.
    port_available_or_die "$PORT"
    [[ -n "$ADMIN_USER" ]] || ADMIN_USER="$DEFAULT_USER"
    [[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,64}$ ]] || die "Admin username: 3–64 letters, digits, . _ -"
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

# Recommended preset: the private panel path is always generated. There is no
# credential to generate — the owner is claimed in the browser.
panel_express_defaults() {
    EXPRESS=1
    : "${MODE:=native}"
    : "${PORT:=$DEFAULT_PORT}"
    PATHPREFIX="$(rand_path)"
    PATH_SET=1
    ADMIN_USER="$DEFAULT_USER"
    TLS_MODE="self"
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
    port_available_or_die "$PORT"
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
    line "  ${GY}No password is set here: the Ready card prints a one-time claim${NC}"
    line "  ${GY}key, and you choose the owner password in the browser.${NC}"
    ADMIN_USER="$(ask "Admin user" "${ADMIN_USER:-$DEFAULT_USER}")"
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
    line "  ${GR}Ready — claim your panel${NC}"
    hr
    kv "Open"  "${WH}${url}claim${NC}"
    if [[ -n "$CLAIM_KEY" ]]; then
        kv "Claim key" "${YL}${CLAIM_KEY}${NC}  ${GY}(one-time)${NC}"
    else
        kv "Claim key" "${RD}not written${NC}  ${GY}(run: ovm owner-claim)${NC}"
    fi
    kv "Login" "${GR}${ADMIN_USER}${NC}"
    kv "Manage" "ovm  (status, logs, backup, restore, TLS, recovery)"
    kv "Logs"   "$logs"
    kv "Data"   "$DATA_DIR"
    line ""
    if [[ "$TLS_MODE" == "self" ]]; then
        info "The browser's certificate warning is expected for a self-signed cert — run ovm https to replace it."
    fi
    info "The key is spent once the panel is claimed. Reprint one with: ovm owner-claim"
    info "No password was set at install time — you choose it in the browser."
    info "Next: install an OVNode (one per VPN server), then Nodes → Add Node in the panel."
    line ""
}

# ── Actions ────────────────────────────────────────────────────────────
do_install() {
    [[ -d "$INSTALL_DIR" ]] && die "Already installed ($INSTALL_DIR). Use: $0 update"
    mkdir -p "$DATA_DIR"
    # Native panel state holds secrets — private from birth (Docker data
    # belongs to uid 1000 instead; doctor --fix normalizes old installs).
    [[ "$MODE" == "docker" ]] || chmod 700 "$DATA_DIR"
    ensure_panel_user
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
        grant_panel_access
        [[ -d "$INSTALL_DIR/frontend/dist" ]] || die "Verified release is missing the prebuilt frontend"
        step "Frontend prebuilt"
        write_systemd_unit
        run_step "Service started" systemctl_bounded restart
    fi

    info "Step 4/4 — Health check and finish"
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 40 \
        || warn "No answer on /health yet — check logs"
    # Minted now, not earlier: the data dir is chowned to the panel user by
    # grant_panel_access (step 3), and the panel reads the key file per claim.
    issue_claim_key
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

    # Deliberately no service-account *migration* here. It was here in 1.0.26
    # and 1.0.28, and it made every update a coin flip: the migration rewrote
    # the unit before the candidate was verified, so a candidate that failed for
    # any other reason left a half-applied migration the failover could not
    # undo. `ovm doctor --fix` is the only path that changes the account.
    #
    # Re-applying the *grant* is a different matter and is required. The step
    # above replaced the whole tree, so on a box where the panel already runs
    # unprivileged the new tree is root-owned again and the service cannot even
    # chdir into it -- measured here as 1.0.30 -> 1.0.31 failing verification
    # with CHDIR: Permission denied, which means every update on a migrated box
    # would break. grant_panel_access is idempotent and changes no ownership of
    # the unit, so it is safe to repeat.
    if [[ "$MODE" != "docker" ]] && ! grep -qE '^User=root\s*$' "/etc/systemd/system/$SYSTEMD_SERVICE" 2>/dev/null; then
        grant_panel_access
        step "Service access re-granted for $PANEL_USER"
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
    confirm "Remove OVManager and stop the service?" n || die "Cancelled."
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
    info "Manage the panel with: ovm  (status, logs, backup, restore, TLS, recovery)"
    if ! can_prompt; then
        fail "Already installed ($INSTALL_DIR). Re-run with:  $0 update"
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
    curl -sSL URL | sudo bash -s -- --yes

  Unattended Install with Docker:
    curl -sSL URL | sudo bash -s -- --docker --yes

COMMANDS
  update [-v VERSION]       Staged update with backup and automatic failover
  recover-update            Recover an update interrupted by reboot/power loss
  uninstall [--purge]       Remove the app; keep data unless --purge
  version-script            Print this installer's version and commit
  help                      Show this help

OPTIONS
  -y, --yes                 Never prompt
  --docker                  Install with Docker
  -h, --help                Show this help

Every other install setting is an OVM_* environment variable — no flag, so an
unattended run and an interactive one cannot disagree:
  OVM_MODE=native|docker        OVM_PORT / OVM_PATH      OVM_ADMIN_USER
  OVM_TLS=self|le|le-ip|custom  OVM_TLS_DOMAIN           OVM_PUBLIC_URL
  OVM_TLS_KEY / OVM_TLS_CERT    OVM_VERSION (update pin)

DEPRECATED (still works)
  These are accepted, but each prints a warning naming what to use instead:
  -p, --pass PASS           has no effect: the owner password is chosen in the
                            browser, with the claim key printed when this ends
  --mode native|docker      use --docker, or OVM_MODE
  --tls 1|2|3|4             use OVM_TLS (1 self, 2 le, 3 le-ip, 4 custom)
  --tls-domain DOMAIN       use OVM_TLS_DOMAIN
  --tls-key FILE            use OVM_TLS_KEY
  --tls-cert FILE           use OVM_TLS_CERT
  -i                        use the "interactive" command

Fresh installs mint a one-time claim key, never a password. Open the Ready
card's URL, paste the key, and choose the owner password in the browser.
ovm owner-claim prints a fresh key at any time before the panel is claimed.

After installation, use ovm (alias: ovmanager) for status, service controls,
logs, backups, HTTPS, diagnostics, recovery, updates, and uninstall.

EXIT
  0 ok   1 error   2 already installed/cancelled   130 interrupted
EOF
    exit 0
}

# One line to stderr per deprecated flag, naming the replacement. Flags are
# cut in a deprecation release: they keep working now and are removed later.
deprecated_flag() {  # deprecated_flag "FLAG" "what to use instead"
    warn "$1 is deprecated — use $2"
}

# `version-script` / `script-version`: which installer did you actually run?
#
# VERSION is embedded; a commit only exists when this file sits in a git
# checkout (a developer run, or a source install). The release tarball is a
# `git archive` with no .git, and a curl-piped installer is a lone file, so
# both report the commit as unknown rather than guessing at one.
script_commit() {
    local dir candidate
    dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || { printf 'unknown'; return 0; }
    candidate="$dir"
    while [[ -n "$candidate" && "$candidate" != "/" ]]; do
        if [[ -e "$candidate/.git" ]]; then
            # Read-only, and only when a checkout is actually there: the
            # common case never invokes git at all.
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
        CLI_GIVEN=1
        case "$1" in
            -p|--pass)    [[ $# -ge 2 ]] || die "-p needs a password"
                           # Accepted and dropped: the owner password is chosen
                           # in the browser, so honouring it would be a lie.
                           deprecated_flag "-p, --pass" "the claim key: the owner password is set in the browser"
                           shift 2 ;;
            --docker)      MODE="docker"; shift ;;
            --mode)        [[ $# -ge 2 ]] || die "--mode needs native or docker"
                           deprecated_flag "--mode" "--docker (or OVM_MODE=native|docker)"
                           MODE="$2"; shift 2 ;;
            --tls)         [[ $# -ge 2 ]] || die "--tls needs 1, 2, 3 or 4 (see --help)"
                           deprecated_flag "--tls" "OVM_TLS=self|le|le-ip|custom"
                           case "$2" in
                               1) TLS_MODE="self" ;;
                               2) TLS_MODE="le" ;;
                               3) TLS_MODE="le-ip" ;;
                               4) TLS_MODE="custom" ;;
                               *) die "--tls needs 1, 2, 3 or 4 (see --help)" ;;
                           esac
                           shift 2 ;;
            --tls-domain)  [[ $# -ge 2 ]] || die "--tls-domain needs a domain"
                           deprecated_flag "--tls-domain" "OVM_TLS_DOMAIN"
                           TLS_DOMAIN="$2"; shift 2 ;;
            --tls-key)     [[ $# -ge 2 ]] || die "--tls-key needs a file"
                           deprecated_flag "--tls-key" "OVM_TLS_KEY"
                           TLS_KEY="$2"; shift 2 ;;
            --tls-cert)    [[ $# -ge 2 ]] || die "--tls-cert needs a file"
                           deprecated_flag "--tls-cert" "OVM_TLS_CERT"
                           TLS_CERT="$2"; shift 2 ;;
            -v|--version)  [[ $# -ge 2 ]] || die "--version needs vX.Y.Z"; PIN="$2"; shift 2 ;;
            -y|--yes) YES=1; shift ;;
            --purge)       PURGE=1; shift ;;
            -i)            deprecated_flag "-i" "the 'interactive' command"
                           ACTION="interactive"; shift ;;
            -h|--help)     usage ;;
            help)          usage ;;
            version-script|script-version) ACTION="version-script"; shift ;;
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
    [[ -z "$TLS_MODE" && -n "${OVM_TLS_MODE:-}" ]] && TLS_MODE="$OVM_TLS_MODE"
    [[ -z "$TLS_MODE" && -n "${OVM_TLS:-}" ]] && TLS_MODE="$OVM_TLS"
    [[ -z "$TLS_DOMAIN" && -n "${OVM_TLS_DOMAIN:-}" ]] && TLS_DOMAIN="$OVM_TLS_DOMAIN"
    [[ -z "$TLS_KEY" && -n "${OVM_TLS_KEY:-}" ]] && TLS_KEY="$OVM_TLS_KEY"
    [[ -z "$TLS_CERT" && -n "${OVM_TLS_CERT:-}" ]] && TLS_CERT="$OVM_TLS_CERT"
    [[ -z "$PIN" && -n "${OVM_VERSION:-}" ]] && PIN="$OVM_VERSION"
    [[ -z "$PUBLIC_URL" && -n "${OVM_PUBLIC_URL:-}" ]] && PUBLIC_URL="$OVM_PUBLIC_URL"
    # Silently ignoring a credential the operator passed is worse than refusing
    # it: say so, once, and let the install continue.
    if [[ -n "${OVM_PASS:-}${OVM_ADMIN_PASS:-}" ]]; then
        deprecated_flag "OVM_PASS / OVM_ADMIN_PASS" "the claim key: the owner password is set in the browser"
    fi
    # Explicit success: the trailing && lines above return 1 when their
    # tests are false, which would trip `set -e` on return.
    return 0
}

main() {
    parse_args "$@"
    apply_env
    if [[ -n "$PIN" ]]; then
        valid_release_version "$PIN" \
            || die "Bad --version '$PIN' (use 1.2.3, v1.2.3, 1.2.3-rc1)"
        VERSION="${PIN#v}"
    fi
    # Before the banner and before root: "which installer did you actually
    # run?" is a support question, and the CDN caches for ~5 minutes so a
    # stale one is normal.
    [[ "$ACTION" == "version-script" ]] && { print_version_script; exit 0; }
    if can_prompt; then
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
            # Express already collected its single answer (the install mode).
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

# Dispatch only when run, not when sourced, so the tests can source the
# functions above and exercise them against a sandbox without installing
# anything. `bash install.sh ...` is unaffected: there $0 is this file.
# Run main when executed as a file OR with no source file at all. The second
# case is the documented pipe form — `curl … | sudo bash -s -- --yes` leaves
# BASH_SOURCE unset, and under `set -u` the bare `"${BASH_SOURCE[0]}"` here was
# an "unbound variable" fatal, so that one-liner never ran at all. Sourcing
# still sets BASH_SOURCE to the sourcing file, which is not $0, so tests that
# source this for its functions are unaffected.
if [[ -z "${BASH_SOURCE[0]:-}" || "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
