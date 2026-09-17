# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Panel-side TLS certificate management.

The panel can own its HTTPS certificate instead of relying on the
SSL_KEYFILE / SSL_CERTFILE environment variables: files written here live in
``DATA_DIR/tls/`` (``privkey.pem`` + ``fullchain.pem``) and are preferred by
``main.py`` on the next start. All endpoints are owner-only because they
control the panel's own TLS identity.

Key material is never returned or logged; every write goes through an atomic
temp-file + ``os.replace`` inside ``DATA_DIR/tls/`` only.
"""

import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from backend.auth.authz import require_owner
from backend.config import config
from backend.data_paths import DATA_DIR
from backend.operations.audit import log_event
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/tls", tags=["TLS"])

ACME_SH = Path.home() / ".acme.sh" / "acme.sh"

MAX_TLS_FILE_SIZE = 1024 * 1024  # 1 MB per uploaded file
ACME_ISSUE_TIMEOUT = 180
ACME_INSTALL_TIMEOUT = 60

RESTART_HINT = (
    "Restart the panel to use the new certificate: "
    "'systemctl restart ovmanager' on a native install, or 'docker restart ovmanager' for Docker."
)

_DOMAIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RenewRequest(BaseModel):
    domain: str | None = None
    email: str | None = None
    use_ip: bool = False


# ── Shared helpers ─────────────────────────────────────────────────────────


def _tls_dir() -> Path:
    return Path(DATA_DIR) / "tls"


def _key_path() -> Path:
    return _tls_dir() / "privkey.pem"


def _cert_path() -> Path:
    return _tls_dir() / "fullchain.pem"


def _meta_path() -> Path:
    return _tls_dir() / "meta.json"


def _ensure_tls_dir() -> Path:
    _tls_dir().mkdir(parents=True, exist_ok=True)
    return _tls_dir()


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    """Write ``data`` next to ``path`` then replace it atomically.

    The temp file is created with mkstemp (0600) inside the TLS directory, so
    nothing is ever written outside DATA_DIR/tls and no half-written file can
    ever become the active certificate.
    """
    _ensure_tls_dir()
    if path.parent.resolve() != _ensure_tls_dir().resolve():
        raise ValueError("refusing to write outside the panel TLS directory")
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            os.fchmod(fh.fileno(), mode)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _write_meta(mode: str) -> None:
    """Best-effort certificate metadata; a failure must not fail the install."""
    meta = json.dumps({"mode": mode, "updated_at": datetime.now(UTC).isoformat()}, indent=2) + "\n"
    try:
        _atomic_write(_meta_path(), meta.encode("utf-8"), 0o644)
    except (OSError, ValueError):
        pass


def _write_managed_files(key_pem: bytes, cert_pem: bytes, mode: str) -> None:
    _ensure_tls_dir()
    _atomic_write(_key_path(), key_pem, 0o600)
    _atomic_write(_cert_path(), cert_pem, 0o644)
    _write_meta(mode)


def _load_certificate(path: Path) -> x509.Certificate | None:
    try:
        with open(path, "rb") as fh:
            return x509.load_pem_x509_certificate(fh.read())
    except Exception:
        return None


def _classify_issuer(cert: x509.Certificate) -> str:
    issuer = cert.issuer.rfc4514_string()
    if "Let's Encrypt" in issuer:
        return "Let's Encrypt"
    if cert.issuer == cert.subject:
        return "self-signed"
    return "custom"


def _process_start_time() -> float:
    try:
        import psutil

        return float(psutil.Process().create_time())
    except Exception:
        pass
    try:
        return os.path.getmtime("/proc/self")
    except OSError:
        return 0.0


def _restart_required(cert_path: str | None) -> bool:
    """True when the active cert was (re)written after this process started."""
    if not cert_path:
        return False
    try:
        return os.path.getmtime(cert_path) > _process_start_time()
    except OSError:
        return False


def _status_payload(mode: str, source: str | None, cert_path: str | None, cert: x509.Certificate | None = None) -> dict:
    expires_days = None
    subject = None
    issued_by = None
    if cert is not None:
        expires_days = (cert.not_valid_after_utc - datetime.now(UTC)).days
        subject = cert.subject.rfc4514_string()
        issued_by = _classify_issuer(cert)
    return {
        "mode": mode,
        "source": source,
        "cert_path": cert_path,
        "expires_days": expires_days,
        "subject": subject,
        "issued_by": issued_by,
        "restart_required": _restart_required(cert_path),
    }


# ── Status ─────────────────────────────────────────────────────────────────


@router.get("/status", response_model=ResponseModel)
def tls_status(user: dict = Depends(require_owner)):
    """Report which certificate the panel will use on its next start.

    Panel-managed files win over SSL_KEYFILE/SSL_CERTFILE, exactly like
    ``main.py``. The key file is never read here.
    """
    managed_cert = _cert_path()
    managed_key = _key_path()
    if managed_cert.is_file() or managed_key.is_file():
        if not managed_cert.is_file() or not managed_key.is_file():
            return ResponseModel(
                success=True,
                msg="The panel-managed TLS files are incomplete (key and certificate are both required).",
                data=_status_payload(
                    "misconfigured", "panel-managed", str(managed_cert) if managed_cert.is_file() else None
                ),
            )
        cert = _load_certificate(managed_cert)
        if cert is None:
            return ResponseModel(
                success=True,
                msg="The panel-managed certificate could not be read.",
                data=_status_payload("misconfigured", "panel-managed", str(managed_cert)),
            )
        return ResponseModel(
            success=True,
            msg="TLS is managed by the panel.",
            data=_status_payload("managed", "panel-managed", str(managed_cert), cert),
        )

    cert_file = (config.SSL_CERTFILE or "").strip()
    key_file = (config.SSL_KEYFILE or "").strip()
    if not cert_file and not key_file:
        return ResponseModel(
            success=True,
            msg="TLS is disabled, so the panel is served over plain HTTP.",
            data=_status_payload("disabled", None, None),
        )
    if not cert_file or not key_file:
        return ResponseModel(
            success=True,
            msg="TLS is only half configured (SSL_CERTFILE and SSL_KEYFILE must be set together).",
            data=_status_payload("misconfigured", "environment", cert_file or None),
        )
    if not Path(cert_file).is_file() or not Path(key_file).is_file():
        return ResponseModel(
            success=True,
            msg="A configured TLS file is missing on disk.",
            data=_status_payload("misconfigured", "environment", cert_file),
        )
    cert = _load_certificate(Path(cert_file))
    if cert is None:
        return ResponseModel(
            success=True,
            msg="The configured TLS certificate could not be read.",
            data=_status_payload("misconfigured", "environment", cert_file),
        )
    return ResponseModel(
        success=True,
        msg="TLS uses certificate files configured through the environment.",
        data=_status_payload("files", "environment", cert_file, cert),
    )


# ── Upload ─────────────────────────────────────────────────────────────────


def _validate_pair(key_bytes: bytes, cert_bytes: bytes) -> tuple[Any, x509.Certificate]:
    if not key_bytes or not cert_bytes:
        raise ValueError("Both the private key and the certificate are required.")
    if len(key_bytes) > MAX_TLS_FILE_SIZE or len(cert_bytes) > MAX_TLS_FILE_SIZE:
        raise ValueError("Each file must be smaller than 1 MB.")
    try:
        private_key = serialization.load_pem_private_key(key_bytes, password=None)
    except TypeError:
        raise ValueError("The private key is encrypted. Remove the passphrase and upload an unencrypted PEM key.") from None
    except Exception:
        raise ValueError("The key file is not a valid PEM private key.") from None
    try:
        cert = x509.load_pem_x509_certificate(cert_bytes)
    except Exception:
        raise ValueError("The certificate file is not a valid PEM certificate.") from None
    key_public = private_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    cert_public = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if key_public != cert_public:
        raise ValueError("The private key does not match the certificate. Upload the key that belongs to this certificate.")
    if cert.not_valid_after_utc <= datetime.now(UTC):
        expired_on = cert.not_valid_after_utc.date().isoformat()
        raise ValueError(f"The certificate expired on {expired_on}. Upload a renewed certificate.")
    return private_key, cert


@router.post("/upload", response_model=ResponseModel)
async def upload_certificate(
    key: UploadFile = File(...),
    cert: UploadFile = File(...),
    user: dict = Depends(require_owner),
):
    """Install an operator-provided key + certificate pair (managed mode)."""
    key_bytes = await key.read(MAX_TLS_FILE_SIZE + 1)
    cert_bytes = await cert.read(MAX_TLS_FILE_SIZE + 1)
    try:
        _, parsed = _validate_pair(key_bytes, cert_bytes)
    except ValueError as exc:
        log_event(None, "tls.upload", actor=user.get("username"), detail=f"rejected: {exc}")
        return ResponseModel(success=False, msg=str(exc), data=None)
    try:
        _write_managed_files(key_bytes, cert_bytes, "custom")
    except (OSError, ValueError) as exc:
        return ResponseModel(success=False, msg=f"Could not save the certificate files: {exc}", data=None)
    log_event(
        None,
        "tls.upload",
        actor=user.get("username"),
        detail=f"custom certificate uploaded, subject={parsed.subject.rfc4514_string()}",
    )
    return ResponseModel(
        success=True,
        msg=f"Certificate installed. {RESTART_HINT}",
        data={"restart_required": True, "cert_path": str(_cert_path()), "key_path": str(_key_path())},
    )


# ── Self-signed ────────────────────────────────────────────────────────────


def _detect_primary_ip() -> str:
    """Best-effort primary IP, mirroring install.sh's ``hostname -I`` first field."""
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5, check=False)
        if result.returncode == 0:
            for token in result.stdout.split():
                try:
                    return str(ipaddress.ip_address(token))
                except ValueError:
                    continue
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def _build_self_signed(common_name: str) -> tuple[bytes, bytes]:
    """RSA 2048 / 10 years, same profile as install.sh's openssl command."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Local"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OVManager"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()), critical=False)
    )
    try:
        alternative: x509.GeneralName = x509.IPAddress(ipaddress.ip_address(common_name))
    except ValueError:
        alternative = x509.DNSName(common_name)
    builder = builder.add_extension(x509.SubjectAlternativeName([alternative]), critical=False)
    cert = builder.sign(private_key, hashes.SHA256())
    key_pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return key_pem, cert.public_bytes(serialization.Encoding.PEM)


@router.post("/self-signed", response_model=ResponseModel)
def generate_self_signed(user: dict = Depends(require_owner)):
    """Regenerate a self-signed certificate for this server's primary IP."""
    try:
        common_name = _detect_primary_ip()
        key_pem, cert_pem = _build_self_signed(common_name)
        _write_managed_files(key_pem, cert_pem, "self-signed")
    except Exception as exc:
        log_event(None, "tls.self_signed", actor=user.get("username"), detail=f"failed: {exc}")
        return ResponseModel(success=False, msg=f"Could not create a self-signed certificate: {exc}", data=None)
    log_event(
        None,
        "tls.self_signed",
        actor=user.get("username"),
        detail=f"self-signed certificate created, CN={common_name}",
    )
    return ResponseModel(
        success=True,
        msg=f"A new self-signed certificate for {common_name} was created. {RESTART_HINT}",
        data={
            "restart_required": True,
            "cert_path": str(_cert_path()),
            "key_path": str(_key_path()),
            "common_name": common_name,
        },
    )


# ── Renew (acme.sh) ────────────────────────────────────────────────────────


def _port_80_busy() -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("0.0.0.0", 80))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def _last_output_line(result: subprocess.CompletedProcess) -> str:
    text = (result.stderr or result.stdout or "").strip()
    if not text:
        return f"acme.sh exited with code {result.returncode}"
    return text.splitlines()[-1].strip()[:200]


def _run_acme(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run([str(ACME_SH), *args], capture_output=True, text=True, timeout=timeout, check=False)


@router.post("/renew", response_model=ResponseModel)
def renew_certificate(payload: RenewRequest, user: dict = Depends(require_owner)):
    """Request a Let's Encrypt certificate through acme.sh (standalone mode)."""
    actor = user.get("username")
    use_ip = bool(payload.use_ip)
    domain = _detect_primary_ip() if use_ip else (payload.domain or "").strip()
    if not domain:
        return ResponseModel(
            success=False,
            msg="Add the domain name to request a Let's Encrypt certificate, or select the IP-address option.",
            data=None,
        )
    if len(domain) > 253 or not _DOMAIN_RE.fullmatch(domain):
        return ResponseModel(
            success=False,
            msg="That domain name is not valid. Use letters, digits, dots and hyphens only.",
            data=None,
        )
    email = (payload.email or "").strip()
    if email and not _EMAIL_RE.fullmatch(email):
        return ResponseModel(
            success=False,
            msg="That email address is not valid. Use a real address so expiry notices can reach you.",
            data=None,
        )
    if not email:
        email = f"acme-{secrets.token_hex(4)}@example.com"

    if not ACME_SH.is_file():
        log_event(None, "tls.renew", actor=actor, detail=f"acme.sh missing, domain={domain}")
        return ResponseModel(
            success=False,
            msg=(
                "acme.sh is not installed on this host, so the panel cannot request a Let's Encrypt certificate. "
                "Install it on the server (curl https://get.acme.sh | sh) and retry — or upload a certificate "
                "issued elsewhere."
            ),
            data={"restart_required": False},
        )
    if _port_80_busy():
        log_event(None, "tls.renew", actor=actor, detail=f"port 80 busy, domain={domain}")
        return ResponseModel(
            success=False,
            msg=(
                "Port 80 is busy, so the Let's Encrypt standalone challenge cannot run. Free port 80 (stop the "
                "service using it, including any reverse proxy in front of the panel) and retry. You can also "
                f"issue it on the host: ~/.acme.sh/acme.sh --issue -d {domain} --standalone."
            ),
            data={"restart_required": False},
        )

    issue_args = ["--issue", "-d", domain, "--standalone", "--accountemail", email]
    if use_ip:
        issue_args += ["--certificate-profile", "shortlived", "--days", "6"]
    try:
        _ensure_tls_dir()
        issue = _run_acme(issue_args, ACME_ISSUE_TIMEOUT)
    except subprocess.TimeoutExpired:
        log_event(None, "tls.renew", actor=actor, detail=f"timeout issuing for {domain}")
        return ResponseModel(
            success=False,
            msg="acme.sh timed out while issuing the certificate. Check the server's network and port 80, then retry.",
            data={"restart_required": False},
        )
    except OSError as exc:
        return ResponseModel(success=False, msg=f"Could not run acme.sh: {exc}", data={"restart_required": False})
    # acme.sh exits 2 when the existing certificate is still fresh ("skip").
    if issue.returncode not in (0, 2):
        reason = _last_output_line(issue)
        log_event(None, "tls.renew", actor=actor, detail=f"issue failed for {domain}: {reason}")
        return ResponseModel(
            success=False,
            msg=(
                f"Let's Encrypt certificate issuance failed: {reason}. Check that the domain points at this "
                "server and that port 80 is reachable from the internet."
            ),
            data={"restart_required": False},
        )

    install_args = ["--install-cert", "-d", domain, "--key-file", str(_key_path()), "--fullchain-file", str(_cert_path())]
    try:
        install = _run_acme(install_args, ACME_INSTALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        log_event(None, "tls.renew", actor=actor, detail=f"timeout installing for {domain}")
        return ResponseModel(
            success=False,
            msg="acme.sh timed out while installing the certificate. Retry, or upload the certificate manually.",
            data={"restart_required": False},
        )
    except OSError as exc:
        return ResponseModel(success=False, msg=f"Could not run acme.sh: {exc}", data={"restart_required": False})
    if install.returncode != 0:
        reason = _last_output_line(install)
        log_event(None, "tls.renew", actor=actor, detail=f"install failed for {domain}: {reason}")
        return ResponseModel(
            success=False,
            msg=f"acme.sh issued the certificate but could not install it: {reason}.",
            data={"restart_required": False},
        )

    try:
        os.chmod(_key_path(), 0o600)
        os.chmod(_cert_path(), 0o644)
    except OSError:
        pass
    parsed = _load_certificate(_cert_path())
    if parsed is None:
        return ResponseModel(
            success=False,
            msg="acme.sh reported success but the installed certificate could not be read. Try again or upload it manually.",
            data={"restart_required": False},
        )
    _write_meta("lets-encrypt")
    log_event(None, "tls.renew", actor=actor, detail=f"Let's Encrypt certificate renewed for {domain}")
    return ResponseModel(
        success=True,
        msg=f"Let's Encrypt certificate for {domain} installed. {RESTART_HINT}",
        data={
            "restart_required": True,
            "cert_path": str(_cert_path()),
            "key_path": str(_key_path()),
            "domain": domain,
            "expires_days": (parsed.not_valid_after_utc - datetime.now(UTC)).days,
        },
    )


# ── Restart ────────────────────────────────────────────────────────────────


def _systemd_unit_exists(unit: str = "ovmanager") -> bool:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False
    try:
        result = subprocess.run([systemctl, "cat", unit], capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _docker_container_running(name: str = "ovmanager") -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    try:
        result = subprocess.run(
            [docker, "inspect", "--format", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _spawn_detached(command: str) -> None:
    """Run a fixed restart command after a short delay, detached from this process.

    The delay gives the HTTP response time to leave the socket before the
    panel (and this process) is restarted.
    """
    subprocess.Popen(
        ["sh", "-c", f"sleep 1; {command}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


@router.post("/restart", response_model=ResponseModel)
def restart_panel(user: dict = Depends(require_owner)):
    """Best-effort panel restart so freshly installed certificates take effect."""
    command = None
    if _systemd_unit_exists():
        command = "systemctl restart ovmanager"
    elif _docker_container_running():
        command = "docker restart ovmanager"
    if command is None:
        log_event(None, "tls.restart", actor=user.get("username"), detail="no automatic restart target found")
        return ResponseModel(
            success=False,
            msg=(
                "Could not restart the panel automatically. Run 'systemctl restart ovmanager' on a native "
                "install, or 'docker restart ovmanager' for Docker."
            ),
            data={"restart_required": True, "restarted": False, "command": "systemctl restart ovmanager"},
        )
    log_event(None, "tls.restart", actor=user.get("username"), detail=command)
    _spawn_detached(command)
    return ResponseModel(
        success=True,
        msg="Restarting the panel now. This page will disconnect and come back in a few seconds.",
        data={"restart_required": True, "restarted": True, "command": command},
    )
