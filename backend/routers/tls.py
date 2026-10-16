"""Panel-side TLS certificate management.

Where the certificate lives is not decided here. ``.env`` declares it —
``SSL_KEYFILE`` and ``SSL_CERTFILE`` — and this module fulfils that
declaration: every write lands at those exact paths, whether the certificate
came from the browser, from ``ovm tls``, or from a hand-placed pair.

That used to be two locations, and the panel silently preferred its own: an
operator who put a certificate at the path in ``.env`` watched the panel keep
serving the old one from ``DATA_DIR/tls/`` with no error anywhere. One
declaration, one location, one writer's worth of confusion removed.

All endpoints are owner-only because they control the panel's own TLS identity.
Key material is never returned or logged; every write goes through an atomic
temp-file + ``os.replace`` beside its target.
"""

import ipaddress
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend import tls_paths
from backend.auth.authz import require_owner
from backend.config import config
from backend.data_paths import DATA_DIR
from backend.db.crud.settings import get_settings, refresh_settings
from backend.db.engine import get_db
from backend.logger import logger
from backend.operations.observability.audit import log_event
from backend.schema import ResponseModel
from backend.validation import validate_domain, validate_email

router = APIRouter(prefix="/tls", tags=["HTTPS"])
https_router = APIRouter(prefix="/https", tags=["HTTPS"])

ACME_SH = Path.home() / ".acme.sh" / "acme.sh"

MAX_TLS_FILE_SIZE = 1024 * 1024  # 1 MB per uploaded file
ACME_ISSUE_TIMEOUT = 180
ACME_INSTALL_TIMEOUT = 60
_CERTIFICATE_LOCK = threading.Lock()

RESTART_HINT = (
    "Restart the panel to use the new certificate: "
    "'systemctl restart ovmanager' on a native install, or 'docker restart ovmanager' for Docker."
)


class RenewRequest(BaseModel):
    domain: str | None = None
    email: str | None = None
    use_ip: bool = False


class TlsSettingsUpdate(BaseModel):
    cert_file: str | None = None
    key_file: str | None = None
    acme_domain: str | None = None
    acme_email: str | None = None
    cert_method: str | None = None


CERT_METHODS = ("selfsigned", "letsencrypt", "none")

# API field → (DB column, .env key). An uncommented line in .env wins over the
# DB value; cert_file/key_file are the API names, ssl_*_file the columns.
_TLS_ENV_KEYS = {
    "cert_file": ("ssl_cert_file", "SSL_CERTFILE"),
    "key_file": ("ssl_key_file", "SSL_KEYFILE"),
    "acme_domain": ("acme_domain", "ACME_DOMAIN"),
    "acme_email": ("acme_email", "ACME_EMAIL"),
    "cert_method": ("cert_method", "CERT_METHOD"),
}


def _env_file_values() -> dict[str, str]:
    """Uncommented ``KEY=VALUE`` pairs from the panel's .env, if it exists."""
    path = Path(str(config.model_config.get("env_file") or ""))
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    except OSError:
        return {}
    return values


@router.get("/settings", response_model=ResponseModel)
def get_tls_settings(db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    """Per-field TLS settings: DB value, .env override, and effective value.

    The DB is canonical. An uncommented ``.env`` line for a field is the
    operator's deliberate override, so that value wins and the UI disables the
    input for it.
    """
    settings = get_settings(db)
    env_values = _env_file_values()
    fields = {}
    for name, (column, env_key) in _TLS_ENV_KEYS.items():
        db_value = getattr(settings, column, None)
        env_value = env_values.get(env_key) or None
        overridden = bool(env_value)
        fields[name] = {
            "db": db_value,
            "env": env_value,
            "effective": env_value if overridden else db_value,
            "overridden": overridden,
            "source": "env" if overridden else ("db" if db_value else None),
        }
    return ResponseModel(
        success=True,
        msg="",
        data={
            "fields": fields,
            "methods": list(CERT_METHODS),
            "restart_required": _restart_required(str(_cert_path())),
        },
    )


@router.put("/settings", response_model=ResponseModel)
def put_tls_settings(
    payload: TlsSettingsUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Write TLS settings to the DB. ``.env`` overrides still win at read time."""
    settings = get_settings(db)
    updates = payload.model_dump(exclude_unset=True)
    method = updates.get("cert_method")
    if method is not None and method not in CERT_METHODS:
        return ResponseModel(success=False, msg=f"Unknown certificate method: {method}", data=None)
    domain = updates.get("acme_domain")
    if domain and not validate_domain(domain):
        return ResponseModel(success=False, msg="That ACME domain is not valid.", data=None)
    email = updates.get("acme_email")
    if email and not validate_email(email):
        return ResponseModel(success=False, msg="That ACME email is not valid.", data=None)
    for name in ("cert_file", "key_file"):
        value = updates.get(name)
        if value:
            if ".." in Path(value).parts:
                return ResponseModel(success=False, msg=f"The {name.replace('_', ' ')} must not contain '..'.", data=None)
            updates[name] = os.path.abspath(value)
    for name, (column, _env_key) in _TLS_ENV_KEYS.items():
        if name in updates:
            setattr(settings, column, updates[name] or None)
    db.commit()
    refresh_settings(db)
    log_event(None, "tls.settings", actor=user.get("username"), detail=",".join(sorted(updates)))
    return ResponseModel(
        success=True,
        msg=f"TLS settings saved. {RESTART_HINT}",
        data={"restart_required": True},
    )


def _tls_dir() -> Path:
    """Where this module keeps its bookkeeping (meta.json, previous-*).

    Not where the certificate lives. That is answered by ``backend.tls_paths``,
    which everyone shares, so a certificate uploaded in the browser lands exactly
    where ``ovm tls`` and uvicorn are already looking.
    """
    return Path(DATA_DIR) / "tls"


def _key_path() -> Path:
    return tls_paths.key_path()


def _cert_path() -> Path:
    return tls_paths.cert_path()


def _meta_path() -> Path:
    return _tls_dir() / "meta.json"


def legacy_pair() -> tuple[Path, Path] | None:
    """The pre-declaration location, when it holds a pair.

    Installs given a certificate before ``.env`` became the declaration have one
    at ``DATA_DIR/tls``. The declared paths now win, so without this they would
    silently fall back to whatever ``.env`` happened to name — a stale
    certificate, with no error anywhere.
    """
    key = _tls_dir() / "privkey.pem"
    cert = _tls_dir() / "fullchain.pem"
    if key.is_file() and cert.is_file():
        return key, cert
    return None


def migrate_legacy_tls() -> dict:
    """Copy a pre-declaration pair onto the declared paths. Never raises.

    Copies rather than moves, and only when the declared path has nothing in
    it: an operator who has already put a certificate where ``.env`` says is not
    going to have it overwritten by one from the old directory.

    Worth doing at all because the declared paths win now. Without it, an
    install whose certificate lives in ``DATA_DIR/tls`` and whose ``.env`` names
    a path that happens to hold nothing would fall back to serving plain HTTP —
    the one outcome that is both silent and total.
    """
    legacy = legacy_pair()
    if legacy is None:
        return {"ok": True, "migrated": False}
    old_key, old_cert = legacy
    new_key, new_cert = _key_path(), _cert_path()
    if new_key.resolve() == old_key.resolve():
        return {"ok": True, "migrated": False}
    if new_key.is_file() and new_cert.is_file():
        return {"ok": True, "migrated": False}
    try:
        _write_managed_files(old_key.read_bytes(), old_cert.read_bytes(), "migrated")
    except Exception as exc:
        return {"ok": False, "error": f"Could not migrate the existing certificate: {exc}"}
    return {"ok": True, "migrated": True, "from": str(old_cert), "to": str(new_cert)}


def _ensure_tls_dir() -> Path:
    _tls_dir().mkdir(parents=True, exist_ok=True)
    return _tls_dir()


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    """Write ``data`` next to ``path`` then replace it atomically.

    The target must be one this module owns: the pair declared in ``.env``, or a
    bookkeeping file beside it in ``DATA_DIR/tls``. The check is on the resolved
    path rather than on the string, so a symlink or a ``..`` in a declaration
    cannot walk the write somewhere else — and because the declarations come
    from a root-owned file the installer wrote, they are not attacker input.

    The temp file is created with mkstemp in the target's own directory, so the
    replace is a rename on one filesystem and a half-written certificate can
    never become the active one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    allowed = {p.resolve() for p in (_key_path(), _cert_path())}
    state = _tls_dir().resolve()
    if resolved.parent == state or resolved == state:
        pass
    elif resolved in allowed:
        pass
    else:
        raise ValueError(f"refusing to write outside the declared certificate paths: {resolved}")
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


def _write_managed_files(key_pem: bytes, cert_pem: bytes, mode: str) -> x509.Certificate:
    """Validate and transactionally activate a certificate pair.

    The previous pair is retained and restored if either active-file write or
    metadata update fails. The process keeps serving its already-loaded pair
    until an explicit restart, so no request can observe a half-written pair.
    """
    _, parsed = _validate_pair(key_pem, cert_pem)
    with _CERTIFICATE_LOCK:
        _tls_dir().mkdir(parents=True, exist_ok=True)
        old_key = _key_path().read_bytes() if _key_path().is_file() else None
        old_cert = _cert_path().read_bytes() if _cert_path().is_file() else None
        old_meta = _meta_path().read_bytes() if _meta_path().is_file() else None
        try:
            _atomic_write(_key_path(), key_pem, 0o600)
            _atomic_write(_cert_path(), cert_pem, 0o644)
            _validate_pair(_key_path().read_bytes(), _cert_path().read_bytes())
            _write_meta(mode)
            if old_key:
                _atomic_write(_tls_dir() / "previous-privkey.pem", old_key, 0o600)
            if old_cert:
                _atomic_write(_tls_dir() / "previous-fullchain.pem", old_cert, 0o644)
        except Exception:
            if old_key is None:
                _key_path().unlink(missing_ok=True)
            else:
                _atomic_write(_key_path(), old_key, 0o600)
            if old_cert is None:
                _cert_path().unlink(missing_ok=True)
            else:
                _atomic_write(_cert_path(), old_cert, 0o644)
            if old_meta is None:
                _meta_path().unlink(missing_ok=True)
            else:
                _atomic_write(_meta_path(), old_meta, 0o644)
            raise
        return parsed


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
    names: list[str] = []
    fingerprint = None
    valid_from = None
    expires_at = None
    if cert is not None:
        expires_days = (cert.not_valid_after_utc - datetime.now(UTC)).days
        subject = cert.subject.rfc4514_string()
        issued_by = _classify_issuer(cert)
        valid_from = cert.not_valid_before_utc.isoformat()
        expires_at = cert.not_valid_after_utc.isoformat()
        fingerprint = cert.fingerprint(hashes.SHA256()).hex(":").upper()
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            names = [str(value) for value in san.get_values_for_type(x509.DNSName)]
            names += [str(value) for value in san.get_values_for_type(x509.IPAddress)]
        except x509.ExtensionNotFound:
            common_names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            names = [common_names[0].value] if common_names else []
    return {
        "mode": mode,
        "source": source,
        "cert_path": cert_path,
        "expires_days": expires_days,
        "expires_at": expires_at,
        "valid_from": valid_from,
        "subject": subject,
        "names": names,
        "fingerprint_sha256": fingerprint,
        "issued_by": issued_by,
        "restart_required": _restart_required(cert_path),
        "previous_available": (_tls_dir() / "previous-privkey.pem").is_file()
        and (_tls_dir() / "previous-fullchain.pem").is_file(),
    }


@router.get("/status", response_model=ResponseModel)
def tls_status(user: dict = Depends(require_owner)):
    """Report which certificate the panel will use on its next start.

    The declared pair (``.env``) wins, exactly like ``main.py``. The key file is
    never read here.
    """
    managed_cert = _cert_path()
    managed_key = _key_path()
    if managed_cert.is_file() or managed_key.is_file():
        if not managed_cert.is_file() or not managed_key.is_file():
            return ResponseModel(
                success=True,
                msg="The declared TLS files are incomplete (key and certificate are both required).",
                data=_status_payload("misconfigured", "declared", str(managed_cert) if managed_cert.is_file() else None),
            )
        cert = _load_certificate(managed_cert)
        if cert is None:
            return ResponseModel(
                success=True,
                msg="The declared certificate could not be read.",
                data=_status_payload("misconfigured", "declared", str(managed_cert)),
            )
        return ResponseModel(
            success=True,
            msg="TLS is declared in .env.",
            data=_status_payload("managed", "declared", str(managed_cert), cert),
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
    cert_public = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if key_public != cert_public:
        raise ValueError("The private key does not match the certificate. Upload the key that belongs to this certificate.")
    now = datetime.now(UTC)
    if cert.not_valid_before_utc > now + timedelta(minutes=5):
        starts_on = cert.not_valid_before_utc.isoformat()
        raise ValueError(f"The certificate is not valid yet (starts {starts_on}). Check the server clock.")
    if cert.not_valid_after_utc <= now:
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
        _, parsed = await run_in_threadpool(_validate_pair, key_bytes, cert_bytes)
    except ValueError as exc:
        log_event(None, "tls.upload", actor=user.get("username"), detail=f"rejected: {exc}")
        return ResponseModel(success=False, msg=str(exc), data=None)
    try:
        await run_in_threadpool(_write_managed_files, key_bytes, cert_bytes, "custom")
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


def _certificate_matches_name(cert: x509.Certificate, expected: str) -> bool:
    """Return whether SAN (or legacy CN fallback) covers a domain/IP exactly."""
    try:
        expected_ip = ipaddress.ip_address(expected)
    except ValueError:
        expected_ip = None
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if expected_ip is not None:
            return expected_ip in san.get_values_for_type(x509.IPAddress)
        return expected.lower() in {name.lower() for name in san.get_values_for_type(x509.DNSName)}
    except x509.ExtensionNotFound:
        common_names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return bool(common_names and common_names[0].value.lower() == expected.lower())


def _detect_primary_ip() -> str:
    """Best-effort public IPv4 for a certificate request, else a routable fallback.

    Not simply the first ``hostname -I`` field: on a host with a docker bridge or
    a cloud metadata NIC that sorts ahead of the public address, that field is a
    private IP and Let's Encrypt refuses it outright. install.sh's public_ip and
    manager.sh's --ip were both fixed for exactly this and the panel's own toggle
    was missed. IPv6 is skipped — the LE paths here are v4.
    """
    routable: str | None = None
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5, check=False)
        if result.returncode == 0:
            for token in result.stdout.split():
                try:
                    addr = ipaddress.ip_address(token)
                except ValueError:
                    continue
                if addr.version != 4:
                    continue
                text_addr = str(addr)
                if not addr.is_private and not addr.is_loopback and not addr.is_link_local:
                    return text_addr
                if routable is None and not addr.is_loopback and not addr.is_link_local:
                    routable = text_addr
    except (OSError, subprocess.SubprocessError):
        pass
    if routable is not None:
        return routable
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def _stored_public_ip() -> str | None:
    """The literal IP address stored in ``.env``'s PUBLIC_URL, when there is one.

    The only public address this host has already written down. A domain there
    is not an address, so it does not count.
    """
    url = (config.PUBLIC_URL or "").strip()
    if not url:
        return None
    host = urlparse(url if "://" in url else f"//{url}").hostname
    if not host:
        return None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def _installer_public_ip() -> str | None:
    """The address install.sh's ``public_ip()`` trusts first, asked the same way.

    Behind NAT no local probe can see the address the internet dials, so the
    panel asks the same two services the installer asks — api.ipify.org, then
    ifconfig.me — with the installer's own shape check and a short timeout.
    """
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                text = response.read(64).decode("ascii", "ignore").strip()
        except Exception:
            continue
        if text and all(char in "0123456789abcdefABCDEF.:" for char in text):
            return text
    return None


def _configured_identity(db: Session | None) -> str | None:
    """The TLS name already stored: an ``.env`` ACME_DOMAIN forces the DB value."""
    env_domain = (_env_file_values().get("ACME_DOMAIN") or "").strip()
    if env_domain:
        return env_domain
    if db is not None:
        try:
            domain = (getattr(get_settings(db), "acme_domain", None) or "").strip()
        except Exception:
            domain = ""
        if domain:
            return domain
    return _stored_public_ip()


def _primary_identity(db: Session | None = None) -> str:
    """Name for a fresh certificate: stored first, detection last.

    Order: DB TLS domain / stored public IP → installer ``public_ip()`` →
    ``_detect_primary_ip()`` → 127.0.0.1.
    """
    return _configured_identity(db) or _installer_public_ip() or _detect_primary_ip()


def _primary_ip() -> str:
    """Address for an IP certificate request — a stored domain does not count."""
    return _stored_public_ip() or _installer_public_ip() or _detect_primary_ip()


def ensure_serving_pair() -> tuple[str, str]:
    """Create a fresh self-signed pair at the serving paths when it is missing.

    Boot rule: the panel serves HTTPS from ``tls_paths`` only. Files that are
    not there — a restored database on a new host, a wiped ``/etc`` — mean a
    new identity generated in place, with the DB record updated to match.
    Never a plain-HTTP listener, never the DB's remembered paths.
    """
    key_path, cert_path = _key_path(), _cert_path()
    if key_path.is_file() and cert_path.is_file():
        return str(key_path), str(cert_path)
    db: Session | None = None
    try:
        from backend.db.engine import SessionLocal

        db = SessionLocal()
    except Exception:
        db = None
    try:
        common_name = _primary_identity(db)
        key_pem, cert_pem = _build_self_signed(common_name)
        with _CERTIFICATE_LOCK:
            _atomic_write(key_path, key_pem, 0o600)
            _atomic_write(cert_path, cert_pem, 0o644)
            _write_meta("self-signed")
        if db is not None:
            try:
                settings = get_settings(db)
                settings.ssl_key_file = str(key_path)
                settings.ssl_cert_file = str(cert_path)
                settings.cert_method = "selfsigned"
                db.commit()
                refresh_settings(db)
            except Exception:
                db.rollback()
                logger.warning("TLS: pair generated, but the settings record could not be updated", exc_info=True)
        logger.warning(
            "TLS: no pair at the serving paths — generated a self-signed certificate for %s at %s",
            common_name,
            cert_path,
        )
    finally:
        if db is not None:
            db.close()
    return str(key_path), str(cert_path)


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
def generate_self_signed(db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    """Regenerate a self-signed certificate for this server's primary identity."""
    try:
        common_name = _primary_identity(db)
        key_pem, cert_pem = _build_self_signed(common_name)
        _write_managed_files(key_pem, cert_pem, "self-signed")
    except Exception as exc:
        log_event(None, "tls.self_signed", actor=user.get("username"), detail=f"failed: {exc}")
        return ResponseModel(success=False, msg=f"Could not create a self-signed certificate: {exc}", data=None)
    refresh_settings(db)
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


def _last_output_line(result: subprocess.CompletedProcess) -> str:
    text = (result.stderr or result.stdout or "").strip()
    if not text:
        return f"acme.sh exited with code {result.returncode}"
    return text.splitlines()[-1].strip()[:200]


def _run_acme(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run([str(ACME_SH), *args], capture_output=True, text=True, timeout=timeout, check=False)


@router.post("/renew", response_model=ResponseModel)
def renew_certificate(
    payload: RenewRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Request a Let's Encrypt certificate through acme.sh (standalone mode)."""
    actor = user.get("username")
    settings = get_settings(db)
    method = getattr(settings, "cert_method", None)
    use_ip = bool(payload.use_ip)
    domain = _primary_ip() if use_ip else (payload.domain or settings.acme_domain or "").strip()
    if not domain:
        if method == "selfsigned":
            return ResponseModel(
                success=False,
                msg="Not applicable: the panel is set to a self-signed certificate.",
                data=None,
            )
        return ResponseModel(
            success=False,
            msg="Add the domain name to request a Let's Encrypt certificate, or select the IP-address option.",
            data=None,
        )
    if use_ip:
        try:
            address = ipaddress.ip_address(domain)
        except ValueError:
            return ResponseModel(success=False, msg="Could not detect a valid server IP address.", data=None)
        if not address.is_global:
            return ResponseModel(
                success=False,
                msg="Automatic IP certificates require a publicly routable server IP.",
                data=None,
            )
    elif not validate_domain(domain):
        return ResponseModel(
            success=False,
            msg="That domain name is not valid. Use letters, digits, dots and hyphens only.",
            data=None,
        )
    email = (payload.email or settings.acme_email or "").strip()
    if email and not validate_email(email):
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

    _ensure_tls_dir()
    staging = Path(tempfile.mkdtemp(prefix=".acme-candidate-", dir=_tls_dir()))
    staged_key = staging / "privkey.pem"
    staged_cert = staging / "fullchain.pem"
    install_args = ["--install-cert", "-d", domain, "--key-file", str(staged_key), "--fullchain-file", str(staged_cert)]
    try:
        install = _run_acme(install_args, ACME_INSTALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        shutil.rmtree(staging, ignore_errors=True)
        log_event(None, "tls.renew", actor=actor, detail=f"timeout installing for {domain}")
        return ResponseModel(
            success=False,
            msg="acme.sh timed out while installing the certificate. Retry, or upload the certificate manually.",
            data={"restart_required": False},
        )
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return ResponseModel(success=False, msg=f"Could not run acme.sh: {exc}", data={"restart_required": False})
    if install.returncode != 0:
        reason = _last_output_line(install)
        shutil.rmtree(staging, ignore_errors=True)
        log_event(None, "tls.renew", actor=actor, detail=f"install failed for {domain}: {reason}")
        return ResponseModel(
            success=False,
            msg=f"acme.sh issued the certificate but could not install it: {reason}.",
            data={"restart_required": False},
        )

    try:
        key_pem = staged_key.read_bytes()
        cert_pem = staged_cert.read_bytes()
        _, candidate_cert = _validate_pair(key_pem, cert_pem)
        if not _certificate_matches_name(candidate_cert, domain):
            raise ValueError(f"issued certificate does not cover {domain}")
        parsed = _write_managed_files(key_pem, cert_pem, "lets-encrypt")
    except Exception as exc:
        log_event(None, "tls.renew", actor=actor, detail=f"candidate rejected for {domain}: {type(exc).__name__}")
        return ResponseModel(
            success=False,
            msg=f"The issued certificate could not be activated; the previous certificate is still active: {exc}",
            data={"restart_required": False, "rolled_back": True},
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    refresh_settings(db)
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


@router.post("/rollback", response_model=ResponseModel)
def rollback_certificate(user: dict = Depends(require_owner)):
    """Restore the certificate pair retained before the last activation."""
    previous_key = _tls_dir() / "previous-privkey.pem"
    previous_cert = _tls_dir() / "previous-fullchain.pem"
    if not previous_key.is_file() or not previous_cert.is_file():
        return ResponseModel(success=False, msg="No previous HTTPS certificate is available.", data=None)
    try:
        parsed = _write_managed_files(previous_key.read_bytes(), previous_cert.read_bytes(), "rollback")
    except Exception as exc:
        log_event(None, "tls.rollback", actor=user.get("username"), detail=f"failed: {type(exc).__name__}")
        return ResponseModel(success=False, msg=f"Could not restore the previous certificate: {exc}", data=None)
    log_event(None, "tls.rollback", actor=user.get("username"), detail="previous certificate restored")
    return ResponseModel(
        success=True,
        msg=f"Previous certificate restored. {RESTART_HINT}",
        data={
            "restart_required": True,
            "rolled_back": True,
            "expires_days": (parsed.not_valid_after_utc - datetime.now(UTC)).days,
        },
    )


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


def _spawn_detached(argv: list[str]) -> None:
    """Run a fixed restart command after a short delay, detached from this process.

    The delay gives the HTTP response time to leave the socket before the
    panel (and this process) is restarted. argv only: no shell is involved,
    so there is no injection surface even if a caller ever passes variables.
    """
    subprocess.Popen(
        ["sh", "-c", 'sleep 1; exec "$@"', "ovmanager-restart", *argv],
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
        command = ["systemctl", "restart", "ovmanager"]
    elif _docker_container_running():
        command = ["docker", "restart", "ovmanager"]
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
    log_event(None, "tls.restart", actor=user.get("username"), detail=" ".join(command))
    _spawn_detached(command)
    return ResponseModel(
        success=True,
        msg="Restarting the panel now. This page will disconnect and come back in a few seconds.",
        data={"restart_required": True, "restarted": True, "command": command},
    )


https_router.add_api_route("/status", tls_status, methods=["GET"], response_model=ResponseModel)
https_router.add_api_route("/existing", upload_certificate, methods=["POST"], response_model=ResponseModel)
https_router.add_api_route("/temporary", generate_self_signed, methods=["POST"], response_model=ResponseModel)
https_router.add_api_route("/automatic", renew_certificate, methods=["POST"], response_model=ResponseModel)
https_router.add_api_route("/rollback", rollback_certificate, methods=["POST"], response_model=ResponseModel)
https_router.add_api_route("/restart", restart_panel, methods=["POST"], response_model=ResponseModel)
