"""OVManager API client for the Telegram bot.

All bot operations go through the panel's HTTP API (never direct DB access).
This ensures audit logging, node synchronization, and validation are applied
consistently whether the user acts through the web UI or the bot.

The API base URL is computed from the bot config (PANEL_URL + dynamic URLPATH).
"""

import httpx
import logging
from bot.config import config

logger = logging.getLogger(__name__)
TIMEOUT = 30.0

# Webhook support: the bot can receive updates via HTTP webhook
# in addition to polling. Set WEBHOOK_URL to enable.
WEBHOOK_URL = config.WEBHOOK_URL or ""


class OVManager:
    """HTTP client for the OVManager panel API."""

    def __init__(self):
        raw = config.resolve_api_url().rstrip("/")
        try:
            from backend.urlpath import get_urlpath
            urlpath = get_urlpath()
            if urlpath:
                self.base = f"{raw}/{urlpath}/api"
            else:
                self.base = f"{raw}/api"
        except Exception:
            self.base = f"{raw}/api"

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make an authenticated HTTP request to the panel API."""
        url = f"{self.base}{path}"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
                resp = await client.request(method, url, **kwargs)
                if resp.status_code == 200:
                    return resp.json()
                logger.warning("API %s %s returned %d: %s", method, path, resp.status_code, resp.text[:200])
                return {"success": False, "msg": f"HTTP {resp.status_code}"}
        except Exception as e:
            logger.error("API error %s %s: %s", method, path, e)
            return {"success": False, "msg": str(e)}

    async def get_users(self) -> list:
        result = await self._request("GET", "/users/")
        data = result.get("data")
        if isinstance(data, dict):
            return data.get("users", [])
        return data if isinstance(data, list) else []

    async def get_user(self, username: str) -> dict:
        users = await self.get_users()
        for u in users:
            if u.get("name") == username:
                return u
        return {}

    async def create_user(self, name: str, days: int = 30, traffic_gb: int = 100, max_users: int = 1) -> dict:
        from datetime import date, timedelta
        exp = date(2099, 12, 31) if days == 0 else date.today() + timedelta(days=days)
        total_bytes = traffic_gb * 1073741824 if traffic_gb > 0 else None

        payload = {
            "name": name,
            "expiry_date": str(exp),
            "total": total_bytes,
            "max_logins": max_users if max_users > 0 else 0,
        }
        result = await self._request("POST", "/users/", json=payload)
        if result.get("success"):
            return {
                "success": True,
                "username": name,
                "days": "Unlimited" if days == 0 else f"{days}d",
                "traffic": "Unlimited" if traffic_gb == 0 else f"{traffic_gb}GB",
                "max_users": "Unlimited" if max_users == 0 else str(max_users),
                "exp": str(exp),
            }
        return {"success": False, "msg": result.get("msg", "Failed to create user")}

    async def update_user(self, username: str, data: dict) -> dict:
        user = await self.get_user(username)
        uuid = user.get("uuid")
        if not uuid:
            return {"success": False, "msg": "User not found"}
        return await self._request("PUT", f"/users/{uuid}", json={
            "name": username,
            **data,
        })

    async def renew_user(self, name: str, days: int, traffic_gb: int, max_users: int) -> dict:
        from datetime import date, timedelta
        user = await self.get_user(name)
        uuid = user.get("uuid")
        if not uuid:
            return {"success": False, "msg": "User not found"}
        exp = date(2099, 12, 31) if days == 0 else date.today() + timedelta(days=days)
        total_bytes = traffic_gb * 1073741824 if traffic_gb > 0 else None
        return await self._request("PUT", f"/users/{uuid}", json={
            "name": name,
            "expiry_date": str(exp),
            "total": total_bytes,
            "max_logins": max_users if max_users > 0 else 0,
            "status": True,
        })

    async def toggle_user_status(self, name: str) -> dict:
        user = await self.get_user(name)
        uuid = user.get("uuid")
        if not uuid:
            return {"success": False, "msg": "User not found"}
        new_status = not user.get("is_active", True)
        result = await self._request("PUT", f"/users/{uuid}/status", json={
            "name": name,
            "status": new_status,
        })
        return {"success": result.get("success", False), "is_active": new_status}

    async def delete_user(self, username: str) -> dict:
        user = await self.get_user(username)
        uuid = user.get("uuid")
        if not uuid:
            return {"success": False, "msg": "User not found"}
        return await self._request("DELETE", f"/users/{uuid}")

    async def get_nodes(self) -> list:
        result = await self._request("GET", "/nodes/")
        data = result.get("data")
        return data if isinstance(data, list) else []

    async def get_node(self, node_id: int) -> dict:
        nodes = await self.get_nodes()
        for n in nodes:
            if n.get("id") == node_id:
                return n
        return {}

    async def get_settings(self) -> dict:
        result = await self._request("GET", "/server/settings")
        data = result.get("data")
        return data if isinstance(data, dict) else {}

    async def _get_settings_from_db(self) -> dict:
        """Fallback: get settings via API (no direct DB access)."""
        return await self.get_settings()

    async def get_admins(self) -> list:
        result = await self._request("GET", "/admin/")
        data = result.get("data")
        return data if isinstance(data, list) else []

    async def download_config(self, username: str, node_name: str) -> str | None:
        """Download .ovpn config for a user via the API."""
        try:
            user = await self.get_user(username)
            uuid = user.get("uuid")
            if not uuid:
                return None
            nodes = await self.get_nodes()
            node = next((n for n in nodes if n.get("name") == node_name), None)
            if not node:
                return None
            url = f"{self.base}/nodes/ovpn/{uuid}/{node['id']}"
            async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    text = resp.text
                    stripped = text.lstrip()[:200].lower()
                    if stripped.startswith("<") or "<html" in stripped:
                        return None
                    return text
            return None
        except Exception:
            return None

    async def get_sub_url(self, username: str) -> str | None:
        """Get the subscription URL for a user."""
        try:
            user = await self.get_user(username)
            uuid = user.get("uuid")
            if not uuid:
                return None
            settings = await self.get_settings()
            sub_prefix = settings.get("subscription_url_prefix", "")
            sub_path = settings.get("subscription_path", "sub")
            base = sub_prefix.rstrip("/") if sub_prefix else self.base.replace("/api", "")
            return f"{base}/{sub_path}/{uuid}"
        except Exception:
            return None
