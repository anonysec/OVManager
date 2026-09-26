"""HTTP client for OVNode API.

Every method follows the same pattern: build URL, send request, check response.
One _request() helper handles all of it.
"""

import time as _time
import warnings as _warnings
from urllib.parse import urlsplit

import requests as _req
from fastapi.responses import Response

from backend.logger import logger

TIMEOUT = 10
LONG_TIMEOUT = 30


# Pinned-CA senders, one session per CA file: hostname checking is OFF but
# chain verification is REQUIRED against exactly the pinned certificate.
# That is the whole point of TOFU pinning — the node's self-signed cert
# names 127.0.0.1 while the panel reaches it over its public IP, so the
# name can never match; the identity proof is the exact cert, not its
# subject. A MITM presenting any other cert still fails closed
# (SSLError → None, no unverified retry).
_pinned_sessions: dict[str, _req.Session] = {}


class _PinnedAdapter(_req.adapters.HTTPAdapter):
    def __init__(self, cafile: str, *args, **kwargs):
        import ssl

        context = ssl.create_default_context(cafile=cafile)
        context.check_hostname = False
        self._pinned_context = context
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._pinned_context
        # urllib3 verifies hostnames itself on top of the context; the pin
        # is the identity proof, not the subject name.
        kwargs["assert_hostname"] = False
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._pinned_context
        kwargs["assert_hostname"] = False
        return super().proxy_manager_for(*args, **kwargs)


def _pinned_sender(cafile: str):
    """Request sender verifying against exactly ``cafile`` (no fallback)."""
    session = _pinned_sessions.get(cafile)
    if session is None:
        session = _req.Session()
        session.mount("https://", _PinnedAdapter(cafile))
        _pinned_sessions[cafile] = session
    return session.request

_MAX_429_WAIT = 60.0

_rpc_last_error: dict[tuple[str, str], str] = {}

_tls_fallback_warned: dict[str, bool] = {}
_TLS_WARNED_CAP = 10_000


def _rpc_failed(address: str, path: str, message: object) -> None:
    msg = str(message)
    key = (address, path)
    if _rpc_last_error.get(key) != msg:
        _rpc_last_error[key] = msg
        logger.warning("Node %s %s: %s", address, path, msg)
    else:
        logger.debug("Node %s %s (still failing): %s", address, path, msg)


def _rpc_ok(address: str, path: str) -> None:
    if _rpc_last_error.pop((address, path), None) is not None:
        logger.warning("Node %s %s: recovered", address, path)


def _retry_after_s(value: object) -> float:
    """Parse a Retry-After header into a capped sleep (seconds)."""
    try:
        wait = float(str(value or "").strip())
    except (TypeError, ValueError):
        return 5.0
    if wait != wait or wait < 1.0:  # NaN or sub-second
        return 1.0
    return min(wait, _MAX_429_WAIT)


def node_client(node, **kw) -> "NodeRequests":
    """Build a NodeRequests for a Node row (single construction site).

    Reuses the per-node connection (backend.node.connection) so repeated
    fan-outs don't pay transport setup per call. Extra kwargs pass through
    to NodeRequests (used by tests to stub clients).
    """
    if kw:
        return NodeRequests(
            address=node.address,
            port=node.port,
            api_key=node.key or "",
            use_tls=node.use_tls,
            server_ca=getattr(node, "server_ca", None),
            **kw,
        )
    return _get_connection(node)


from backend.node.connection import get_connection as _get_connection  # noqa: E402


class NodeRequests:
    __slots__ = ("address", "headers", "scheme", "tls_verified", "_verify")

    def __init__(self, address: str, port: int, api_key: str, use_tls: bool = False, server_ca: str | None = None, **_):
        raw = str(address or "").strip()
        parsed = urlsplit(raw if "://" in raw else f"//{raw}")
        host = parsed.hostname
        if not host:
            raise ValueError("Node address must contain a hostname or IP")
        try:
            parsed_port = parsed.port
        except ValueError as exc:
            raise ValueError("Node address contains an invalid port") from exc
        target_port = parsed_port or int(port)
        host_for_url = f"[{host}]" if ":" in host and not host.startswith("[") else host
        self.address = f"{host_for_url}:{target_port}"
        self.headers = {"key": api_key}
        self.scheme = parsed.scheme if parsed.scheme in ("http", "https") else ("https" if use_tls else "http")
        self._verify = "pinned"
        if self.scheme == "https" and server_ca:
            from backend.operations.node_pki import ca_file_for

            node_id = _.get("node_id")
            self._verify = ca_file_for(node_id, server_ca) if node_id is not None else None
            if self._verify is None:
                raise ValueError("Node has a pinned certificate but it is not a PEM certificate")
        self.tls_verified: bool | None = None

    @property
    def tls_mode(self) -> str:
        """Connection security for the UI: plain / verified /
        unverified-self-signed / unknown (never connected)."""
        if self.scheme != "https":
            return "plain"
        if self.tls_verified is True:
            return "verified"
        if self.tls_verified is False:
            return "unverified-self-signed"
        return "unknown"

    def _url(self, path: str) -> str:
        return f"{self.scheme}://{self.address}{path}"

    def _note_tls_fallback(self, path: str, exc: Exception) -> None:
        """Warn about the unverified-TLS fallback, loudly once per node.

        Expected for self-signed nodes (the installer default). Poll loops
        would spam every tick, so repeats go to debug — but the API key
        crosses the wire to an unverified endpoint from here, so the first
        occurrence must stay visible. The same first occurrence also writes
        one ``node.tls_unverified`` audit event per address.
        """
        if self.address not in _tls_fallback_warned:
            if len(_tls_fallback_warned) >= _TLS_WARNED_CAP:
                _tls_fallback_warned.pop(next(iter(_tls_fallback_warned)))
            _tls_fallback_warned[self.address] = True
            logger.warning(
                "Node %s: TLS cert not publicly trusted (%s) — falling back "
                "to UNVERIFIED TLS (self-signed?). API key is sent without "
                "MITM protection; switch the node to Let's Encrypt.",
                self.address,
                exc,
            )
            try:
                from backend.operations.audit import log_event

                log_event(
                    None,
                    "node.tls_unverified",
                    actor=None,
                    target=self.address,
                    detail="API key sent over unverified TLS (self-signed node?)",
                )
            except Exception:
                pass  # audit is best-effort; never break the request
        else:
            logger.debug("Node %s %s: TLS verify failed — retrying unverified", self.address, path)

    def _request(self, method: str, path: str, **kw) -> dict | None:
        """Send request, return parsed JSON or None on failure.

        TLS policy: with a pinned ``server_ca``, HTTPS is verified against
        exactly that certificate and an SSL failure fails closed (a MITM
        between panel and node must not get the API key). Without a pin
        (legacy self-signed node not yet pinned), verified-first with one
        unverified retry and a ONE-TIME loud warning. ``tls_verified``
        records which path was used so the UI can show it.

        ``require_success=False`` returns the node's envelope even when it
        answers ``success: false`` (e.g. an update refusal), so callers can
        surface the node's own message; transport errors still return None.
        """
        require_success = bool(kw.pop("require_success", True))
        kw.setdefault("timeout", TIMEOUT)
        if self.scheme != "https":
            return self._send_plain(method, path, require_success=require_success, **kw)
        if isinstance(self._verify, str) and self._verify != "pinned":
            # Pinned CA: verify against that exact certificate via a session
            # whose context requires the chain but skips the hostname (the
            # cert names localhost while we dial the public IP). No fallback:
            # a non-matching cert fails closed here.
            try:
                result = self._send(
                    method, path, require_success=require_success, sender=_pinned_sender(self._verify), **kw
                )
                self.tls_verified = True
                return result
            except _req.exceptions.SSLError as e:
                logger.error(
                    "Node %s %s: TLS cert does not match the pinned certificate (%s) — refusing to connect. "
                    "Re-add or re-pin the node if the certificate was rotated.",
                    self.address,
                    path,
                    e,
                )
                return None
            except Exception as e:
                _rpc_failed(self.address, path, e)
                return None
        try:
            result = self._send(method, path, verify=True, require_success=require_success, **kw)
            self.tls_verified = True
            return result
        except _req.exceptions.SSLError as e:
            self._note_tls_fallback(path, e)
            try:
                with _warnings.catch_warnings():
                    _warnings.simplefilter("ignore")
                    result = self._send(method, path, verify=False, require_success=require_success, **kw)
                    self.tls_verified = False
                    return result
            except Exception as e2:
                _rpc_failed(self.address, path, e2)
                return None
        except Exception as e:
            _rpc_failed(self.address, path, e)
            return None

    def _send_plain(self, method: str, path: str, **kw) -> dict | None:
        """Non-TLS request path (use_tls=False)."""
        try:
            return self._send(method, path, **kw)
        except Exception as e:
            _rpc_failed(self.address, path, e)
            return None

    def _send(self, method: str, path: str, require_success: bool = True, sender=None, **kw) -> dict | None:
        """Send request, return parsed JSON or None on failure.

        A single Retry-After-aware retry on 429 keeps bulk fan-outs (create
        100 users → 100 cert ops) from hard-failing when they brush the
        node's cert-op bucket: slow down once instead of reporting failure.
        Runs in a threadpool worker, so the sleep never blocks the loop.

        ``sender`` overrides the transport: pinned-CA sessions pass
        ``session.request`` here so verification rides the pinned context.
        """
        transport = sender or getattr(_req, method)
        if sender is not None:
            r = transport(method, self._url(path), headers=self.headers, **kw)
        else:
            r = transport(self._url(path), headers=self.headers, **kw)
        if r.status_code == 429:
            wait = _retry_after_s(r.headers.get("Retry-After"))
            logger.warning(
                "Node %s %s: rate-limited (429) — retrying once in %.0fs",
                self.address,
                path,
                wait,
            )
            _time.sleep(wait)
            if sender is not None:
                r = transport(method, self._url(path), headers=self.headers, **kw)
            else:
                r = transport(self._url(path), headers=self.headers, **kw)
        if r.status_code != 200:
            _rpc_failed(self.address, path, f"HTTP {r.status_code}")
            return None
        data = r.json()
        if not data.get("success") and require_success:
            _rpc_failed(self.address, path, data.get("msg"))
            return None
        _rpc_ok(self.address, path)
        return data

    def check_node(self, **settings) -> bool:
        r = self._request("get", "/sync/status", json=settings)
        return bool(r)

    def get_node_info(self, **settings) -> dict:
        return (self._request("get", "/sync/status", json=settings) or {}).get("data", {})

    def get_usage(self, timeout: float = LONG_TIMEOUT) -> dict:
        """Return per-user traffic counters from the node."""
        return (self._request("get", "/sync/usage", timeout=timeout) or {}).get("data", {})

    def update_config(
        self,
        *,
        tunnel_address: str,
        protocol: str,
        ovpn_port: int,
        set_new_setting: bool = True,
        dns1: str | None = None,
        dns2: str | None = None,
        enable_ipv6: bool | None = None,
        ipv6_prefix: str | None = None,
        extra_ports: str | None = None,
        return_envelope: bool = False,
    ) -> bool | dict | None:
        """Apply OpenVPN endpoint settings on the node.

        dns1/dns2, enable_ipv6/ipv6_prefix and extra_ports are optional
        per-node settings. They are included in the payload only when
        provided: omitting them leaves the node's current values untouched,
        and an old node simply ignores them. ``enable_ipv6=False`` and the
        empty string for ``extra_ports`` (clear the extras) are real values
        and are sent as such — only ``None`` means "unchanged".

        With ``return_envelope=True`` the node's whole response envelope is
        returned (None on transport failure) so callers can surface the
        node's own message; the default keeps the historical bool result.
        """
        payload = {
            "tunnel_address": tunnel_address or "",
            "protocol": protocol,
            "ovpn_port": int(ovpn_port),
            "set_new_setting": bool(set_new_setting),
        }
        if dns1 is not None:
            payload["dns1"] = dns1
        if dns2 is not None:
            payload["dns2"] = dns2
        if enable_ipv6 is not None:
            payload["enable_ipv6"] = bool(enable_ipv6)
        if ipv6_prefix is not None:
            payload["ipv6_prefix"] = ipv6_prefix
        if extra_ports is not None:
            payload["extra_ports"] = extra_ports
        if return_envelope:
            return self._request("post", "/sync/config", json=payload, timeout=LONG_TIMEOUT, require_success=False)
        return self._request("post", "/sync/config", json=payload, timeout=LONG_TIMEOUT) is not None

    def restart_vpn(self) -> dict | None:
        """Ask the node to restart its OpenVPN service (POST /sync/restart).

        Returns the node's response envelope even when the restart failed
        (``success: false`` + ``msg`` carry the reason), so the caller can
        surface the node's own message; None means a transport-level failure.
        """
        return self._request("post", "/sync/restart", timeout=LONG_TIMEOUT, require_success=False)

    def renew_server_cert(self) -> dict | None:
        """Ask the node to renew its OpenVPN server certificate.

        POST /sync/renew-cert. Returns the node's envelope even on refusal
        (``success: false`` + ``msg``); None means a transport failure.
        """
        return self._request("post", "/sync/renew-cert", timeout=LONG_TIMEOUT, require_success=False)

    def trigger_update(self) -> dict | None:
        """Ask the node to run its self-update (POST /sync/update).

        Returns the node's response envelope even when the node refuses
        (Docker installs answer success=false), so callers surface the
        node's own guidance. None means a transport-level failure.
        """
        return self._request("post", "/sync/update", timeout=LONG_TIMEOUT, require_success=False)

    def create_user(self, name: str, max_logins: int = 1, uid: str = None) -> bool:
        data = {"name": name, "max_logins": max_logins}
        if uid:
            data["id"] = uid
        return self._request("post", "/sync/user", json=data, timeout=180) is not None

    def change_user_status(self, name: str, status: bool, max_logins: int = None, uid: str = None) -> bool:
        data = {"name": name, "status": "activate" if status else "deactivate"}
        if uid:
            data["id"] = uid
        if max_logins is not None:
            data["max_logins"] = max_logins
        return self._request("put", "/sync/user", json=data, timeout=LONG_TIMEOUT) is not None

    def delete_user(self, uid: str) -> bool:
        return self._request("delete", f"/sync/user/{uid}", timeout=120) is not None

    def set_user_limit(self, uid: str, max_logins: int) -> bool:
        return (
            self._request("put", "/sync/user/limit", json={"id": uid, "max_logins": max_logins}, timeout=LONG_TIMEOUT) is not None
        )

    def disconnect_user(self, uid: str, only_stale: bool = False) -> dict:
        kw = {"params": {"only_stale": "true"}} if only_stale else {}
        r = self._request("post", f"/sync/user/{uid}/disconnect", timeout=LONG_TIMEOUT, **kw)
        return (r or {}).get("data", {})

    def reset_usage(self, uid: str) -> bool:
        """Zero a user's banked counters on the node. Best-effort: the DB
        reset is authoritative; a failed node push only delays (never
        resurrects — the collector rebaselines totals it hasn't seen)."""
        r = self._request("post", f"/sync/user/{uid}/reset-usage", timeout=LONG_TIMEOUT)
        return bool((r or {}).get("success"))

    def _get_raw(self, path: str, **kw) -> bytes | None:
        """GET raw bytes with the same TLS policy as _request.

        Verified first (LE nodes); one unverified retry with a warning for
        self-signed nodes. Returns None on any failure.
        """
        url = self._url(path)
        headers = kw.pop("headers", self.headers)
        if self.scheme != "https":
            try:
                r = _req.get(url, headers=headers, **kw)
            except Exception as e:
                logger.error("Node %s %s: %s", self.address, path, e)
                return None
        elif isinstance(self._verify, str) and self._verify != "pinned":
            # Pinned CA via the pinned session (chain required, hostname
            # unchecked — same policy as _request). No fallback.
            try:
                r = _pinned_sender(self._verify)("get", url, headers=headers, **kw)
                self.tls_verified = True
            except _req.exceptions.SSLError as e:
                logger.error(
                    "Node %s %s: TLS cert does not match the pinned certificate (%s) — refusing to connect.",
                    self.address,
                    path,
                    e,
                )
                return None
            except Exception as e:
                logger.error("Node %s %s: %s", self.address, path, e)
                return None
        else:
            kw.setdefault("verify", True)
            try:
                r = _req.get(url, headers=headers, **kw)
                self.tls_verified = True
            except _req.exceptions.SSLError as e:
                self._note_tls_fallback(path, e)
                try:
                    with _warnings.catch_warnings():
                        _warnings.simplefilter("ignore")
                        kw["verify"] = False
                        r = _req.get(url, headers=headers, **kw)
                        self.tls_verified = False
                except Exception as e2:
                    logger.error("Node %s %s: %s", self.address, path, e2)
                    return None
            except Exception as e:
                logger.error("Node %s %s: %s", self.address, path, e)
                return None
        body = r.content
        if r.status_code == 200 and (body.lstrip().startswith(b"client") or b"<ca>" in body):
            return body
        logger.error("Node %s %s: invalid response", self.address, path)
        return None

    def download_ovpn_client(self, uid: str) -> Response | None:
        body = self._get_raw(
            f"/sync/download/ovpn/{uid}",
            headers={**self.headers, "Accept": "application/x-openvpn-profile"},
            timeout=120,
        )
        if body is None:
            logger.error("Node %s OVPN %s: invalid response", self.address, uid)
            return None
        return Response(
            content=body,
            media_type="application/x-openvpn-profile",
            headers={"Content-Disposition": f'attachment; filename="{uid}.ovpn"'},
        )

    def get_sessions(self, common_name: str = None, hours: int = 8) -> dict:
        params = {"hours": hours}
        if common_name:
            params["common_name"] = common_name
        r = self._request("get", "/sync/sessions", params=params, timeout=LONG_TIMEOUT)
        return (r or {}).get("data", {})

    def get_logs(self, level: str = "WARNING", limit: int = 100) -> dict:
        """Fetch the node's in-memory log ring (remote diagnostics)."""
        level = (level or "WARNING").upper()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            level = "WARNING"
        limit = max(1, min(int(limit or 100), 500))
        r = self._request("get", "/sync/logs", params={"level": level, "limit": limit}, timeout=LONG_TIMEOUT)
        return (r or {}).get("data", {})

    def download_ovpn_bytes(self, uid: str) -> bytes | None:
        """Return the raw .ovpn file bytes (for ZIP bundling etc.)."""
        body = self._get_raw(
            f"/sync/download/ovpn/{uid}",
            headers={**self.headers, "Accept": "application/x-openvpn-profile"},
            timeout=120,
        )
        if body is None:
            logger.error("Node %s OVPN bytes %s: invalid response", self.address, uid)
        return body
