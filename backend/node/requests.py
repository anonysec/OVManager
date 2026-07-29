"""HTTP client for OVNode API.

Every method follows the same pattern: build URL, send request, check response.
One _request() helper handles all of it.
"""

import requests as _req
from fastapi.responses import Response
from backend.logger import logger

TIMEOUT = 10
LONG_TIMEOUT = 30


class NodeRequests:
    __slots__ = ("address", "headers", "scheme")

    def __init__(self, address: str, port: int, api_key: str, use_tls: bool = False, **_):
        self.address = f"{address}:{port}"
        self.headers = {"key": api_key}
        self.scheme = "https" if use_tls else "http"

    def _url(self, path: str) -> str:
        return f"{self.scheme}://{self.address}{path}"

    def _request(self, method: str, path: str, **kw) -> dict | None:
        """Send request, return parsed JSON or None on failure."""
        kw.setdefault("timeout", TIMEOUT)
        try:
            r = getattr(_req, method)(self._url(path), headers=self.headers, **kw)
            if r.status_code != 200:
                logger.error("Node %s %s → %s", self.address, path, r.status_code)
                return None
            data = r.json()
            if not data.get("success"):
                logger.error("Node %s %s: %s", self.address, path, data.get("msg"))
                return None
            return data
        except Exception as e:
            logger.error("Node %s %s: %s", self.address, path, e)
            return None

    # ── Node management ──────────────────────────────────────────

    def check_node(self, **settings) -> bool:
        r = self._request("get", "/sync/status", json=settings)
        return bool(r)

    def get_node_info(self, **settings) -> dict:
        return (self._request("get", "/sync/status", json=settings) or {}).get("data", {})

    # ── User operations ──────────────────────────────────────────

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
        return self._request("delete", f"/sync/user/{uid}") is not None

    def set_user_limit(self, uid: str, max_logins: int) -> bool:
        return self._request("put", "/sync/user/limit", json={"id": uid, "max_logins": max_logins}, timeout=LONG_TIMEOUT) is not None

    def disconnect_user(self, uid: str) -> dict:
        r = self._request("post", f"/sync/user/{uid}/disconnect")
        return (r or {}).get("data", {})

    # ── OVPN download ────────────────────────────────────────────

    def download_ovpn_client(self, uid: str) -> Response | None:
        try:
            r = _req.get(self._url(f"/sync/download/ovpn/{uid}"), headers={**self.headers, "Accept": "application/x-openvpn-profile"}, timeout=120)
            body = r.content
            if r.status_code == 200 and (body.lstrip().startswith(b"client") or b"<ca>" in body):
                return Response(content=body, media_type="application/x-openvpn-profile",
                                headers={"Content-Disposition": f'attachment; filename="{uid}.ovpn"'})
            logger.error("Node %s OVPN %s: invalid response", self.address, uid)
        except Exception as e:
            logger.error("Node %s OVPN %s: %s", self.address, uid, e)
        return None

    # ── Sessions & usage ─────────────────────────────────────────

    def get_sessions(self, common_name: str = None, hours: int = 8) -> dict:
        params = {"hours": hours}
        if common_name:
            params["common_name"] = common_name
        r = self._request("get", "/sync/sessions", params=params, timeout=LONG_TIMEOUT)
        return (r or {}).get("data", {})
