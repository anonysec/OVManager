# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Authenticated HTTP client for the panel API."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx2

from bot.config import config

log = logging.getLogger(__name__)
TIMEOUT = httpx2.Timeout(30.0, connect=8.0)

_client: httpx2.AsyncClient | None = None


def _urlpath() -> str:
    try:
        from backend.urlpath import get_urlpath

        return (get_urlpath() or "").strip("/")
    except Exception:
        return ""


def api_root() -> str:
    base = config.resolve_api_url().rstrip("/")
    prefix = _urlpath()
    return f"{base}/{prefix}/api" if prefix else f"{base}/api"


def client() -> httpx2.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx2.AsyncClient(timeout=TIMEOUT, verify=True)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def login(username: str, password: str) -> str | None:
    url = f"{api_root()}/login"
    try:
        resp = await client().post(url, data={"username": username, "password": password})
        if resp.status_code != 200:
            log.warning("Login failed: HTTP %s", resp.status_code)
            return None
        return resp.json().get("access_token")
    except Exception as exc:
        log.error("Login error: %s", exc)
        return None


class Panel:
    def __init__(self, token: str):
        self.token = token
        # Last HTTP status of request()/download_ovpn (None = no call yet).
        # Handlers use it to tell "panel unreachable" (0) apart from an
        # empty-but-healthy response — get_users() returns [] in both cases.
        self.last_status: int | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Requested-With": "ovmanager-bot"}

    async def request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{api_root()}{path}"
        try:
            resp = await client().request(method, url, headers=self._headers(), **kwargs)
        except Exception as exc:
            log.error("API %s %s failed: %s", method, path, exc)
            self.last_status = 0
            return {"success": False, "msg": "Panel is unreachable.", "status": 0}
        self.last_status = resp.status_code
        if resp.status_code == 200:
            try:
                body = resp.json()
            except Exception:
                return {"success": True, "data": resp.content, "raw": True, "status": 200}
            if isinstance(body, dict):
                body.setdefault("status", 200)
                return body
            return {"success": True, "data": body, "status": 200}
        detail = ""
        try:
            payload = resp.json()
            detail = payload.get("detail") or payload.get("msg") or ""
            if isinstance(detail, list):
                detail = "; ".join(str(item.get("msg") or item) for item in detail)
        except Exception:
            detail = resp.text[:180]
        log.warning("API %s %s → %s %s", method, path, resp.status_code, detail)
        return {"success": False, "msg": detail or f"HTTP {resp.status_code}", "status": resp.status_code}

    # ── Users ────────────────────────────────────────────────────────

    async def get_users(self, search: str | None = None) -> list[dict]:
        path = "/users/"
        if search and search.strip():
            from urllib.parse import quote

            path += f"?search={quote(search.strip())}"
        result = await self.request("GET", path)
        data = result.get("data")
        if isinstance(data, dict):
            return list(data.get("users") or [])
        return list(data) if isinstance(data, list) else []

    async def get_user(self, *, uuid: str | None = None, name: str | None = None) -> dict | None:
        if name and not uuid:
            # Server-side exact match first (one small query, not the table).
            for user in await self.get_users(search=name):
                if (user.get("name") or "").lower() == name.lower():
                    return user
            return None
        users = await self.get_users()
        if uuid:
            for user in users:
                if user.get("uuid") == uuid:
                    return user
        if name:
            needle = name.lower()
            for user in users:
                if (user.get("name") or "").lower() == needle:
                    return user
        return None

    async def search_users(self, query: str) -> list[dict]:
        needle = query.strip().lower()
        if not needle:
            return []
        users = await self.get_users(search=query.strip())
        exact = [u for u in users if (u.get("name") or "").lower() == needle]
        if exact:
            return exact
        return [u for u in users if needle in (u.get("name") or "").lower()]

    async def next_username(self) -> str | None:
        result = await self.request("GET", "/users/next-username")
        if not result.get("success"):
            return None
        data = result.get("data") or {}
        return data.get("username")

    async def create_user(self, name: str, days: int, traffic_gb: int, max_logins: int) -> dict:
        exp = date(2099, 12, 31) if days == 0 else date.today() + timedelta(days=days)
        payload = {
            "name": name,
            "expiry_date": exp.isoformat(),
            "total": None if traffic_gb == 0 else int(traffic_gb) * 1073741824,
            "max_logins": 0 if max_logins == 0 else int(max_logins),
        }
        return await self.request("POST", "/users/", json=payload)

    async def extend_user(self, uuid: str, *, days: int = 0, bytes_: int = 0) -> dict:
        return await self.request("POST", f"/users/{uuid}/extend", json={"days": days, "bytes": bytes_})

    async def update_user(self, uuid: str, name: str, **fields: Any) -> dict:
        return await self.request("PUT", f"/users/{uuid}", json={"name": name, **fields})

    async def set_status(self, uuid: str, name: str, active: bool) -> dict:
        return await self.request("PUT", f"/users/{uuid}/status", json={"name": name, "status": active})

    async def reset_usage(self, uuid: str) -> dict:
        return await self.request("POST", f"/users/{uuid}/reset-usage")

    async def disconnect(self, uuid: str) -> dict:
        return await self.request("POST", f"/users/{uuid}/disconnect")

    async def delete_user(self, uuid: str) -> dict:
        return await self.request("DELETE", f"/users/{uuid}")

    async def restore_user(self, uuid: str) -> dict:
        """Undo a recent delete (panel keeps a ≤120s undo window)."""
        return await self.request("POST", f"/users/{uuid}/restore")

    # ── Nodes / system ───────────────────────────────────────────────

    async def get_nodes(self) -> list[dict]:
        result = await self.request("GET", "/nodes/")
        data = result.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.get("nodes") or [])
        return []

    async def node_status(self, node_id: int) -> dict:
        """Full result dict (check success/data) for the node drill-down."""
        return await self.request("GET", f"/nodes/{node_id}/status/")

    async def get_settings(self) -> dict:
        result = await self.request("GET", "/server/settings")
        data = result.get("data")
        return data if isinstance(data, dict) else {}

    async def get_info(self) -> dict:
        result = await self.request("GET", "/server/info")
        data = result.get("data")
        return data if isinstance(data, dict) else {}

    async def get_admins(self) -> list[dict]:
        result = await self.request("GET", "/admin/")
        data = result.get("data")
        if isinstance(data, list):
            return data
        return []

    async def get_sub_url(self, uuid: str) -> str | None:
        settings = await self.get_settings()
        prefix = (settings.get("subscription_url_prefix") or "").rstrip("/")
        path = (settings.get("subscription_path") or "sub").strip("/")
        if not prefix:
            prefix = config.resolve_api_url().rstrip("/")
            extra = _urlpath()
            if extra:
                prefix = f"{prefix}/{extra}"
        if not uuid:
            return None
        return f"{prefix}/{path}/{uuid}" if path else f"{prefix}/{uuid}"

    async def download_ovpn(self, uuid: str, node_id: int) -> bytes | None:
        url = f"{api_root()}/nodes/ovpn/{uuid}/{node_id}"
        try:
            resp = await client().get(url, headers=self._headers())
        except Exception as exc:
            log.error("OVPN download failed: %s", exc)
            return None
        if resp.status_code != 200:
            return None
        content_type = (resp.headers.get("content-type") or "").lower()
        if "html" in content_type:
            return None
        body = resp.content
        if body.lstrip()[:15].lower().startswith(b"<"):
            return None
        return body
