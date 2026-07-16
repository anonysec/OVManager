import requests
from fastapi.responses import Response
from backend.logger import logger


class NodeRequests:
    """Handles requests to the node API."""

    def __init__(
        self,
        address: str,
        port: int,
        api_key: str,
        tunnel_address: str = "ovpanel.com",
        protocol: str = "tcp",
        ovpn_port: int = 1194,
        set_new_setting: bool = False,
    ):
        self.address = f"{address}:{port}"
        self.headers = {"key": api_key}
        self.tunnel_address = tunnel_address
        self.protocol = protocol
        self.ovpn_port = ovpn_port
        self.set_new_setting = set_new_setting
        # TODO: support https per-node (add field to Node model + UI)
        self.scheme = "http"

    def check_node(self) -> bool:
        """Checks the node status and sets new settings if necessary."""
        api = f"{self.scheme}://{self.address}/sync/status"
        try:
            data = {
                "tunnel_address": self.tunnel_address,
                "protocol": self.protocol,
                "ovpn_port": self.ovpn_port,
                "set_new_setting": self.set_new_setting,
            }
            resp = requests.get(api, headers=self.headers, json=data, timeout=5)
            if resp.status_code != 200:
                logger.error(f"Node {self.address} returned {resp.status_code}")
                return False
            response = resp.json()
            if response.get("success"):
                return True
            else:
                logger.error(f"Node {self.address} is not reachable: {response.get('msg')}")
                return False
        except Exception as e:
            logger.error(f"Error checking node {self.address}: {e}")
            return False

    def get_node_info(self, timeout: int | float = 10) -> dict:
        api = f"{self.scheme}://{self.address}/sync/status"
        try:
            data = {
                "tunnel_address": self.tunnel_address,
                "protocol": self.protocol,
                "ovpn_port": self.ovpn_port,
                "set_new_setting": self.set_new_setting,
            }
            response = requests.get(
                api, headers=self.headers, json=data, timeout=timeout
            ).json()
            if response.get("success"):
                return response.get("data")
            else:
                logger.error(
                    f"Failed to get node info on {self.address}: {response.get('msg')}"
                )
                return {}
        except Exception as e:
            logger.error(f"Error getting node info on {self.address}: {e}")
            return {}

    def create_user(self, name: str, max_logins: int = 1) -> bool:
        api = f"{self.scheme}://{self.address}/sync/user"
        data = {"name": name, "max_logins": max_logins}
        try:
            resp = requests.post(
                api, headers=self.headers, json=data, timeout=180
            )
            if resp.status_code != 200:
                logger.error(f"Node {self.address} create_user returned HTTP {resp.status_code}: {resp.text[:200]}")
                return False
            response = resp.json()
            if response.get("success"):
                return True
            else:
                logger.error(
                    f"Failed to create user on node {self.address}: {response.get('msg')}"
                )
                return False
        except Exception as e:
            logger.error(f"Error creating user on node {self.address}: {e}")
            return False

    def change_user_status(self, name, status, max_logins: int | None = None):
        api = f"{self.scheme}://{self.address}/sync/user"
        try:
            data = {"name": name, "status": "activate" if status else "deactivate"}
            if max_logins is not None:
                data["max_logins"] = max_logins
            resp = requests.put(
                api, headers=self.headers, json=data, timeout=60
            )
            if resp.status_code != 200:
                logger.error(f"Node {self.address} change_user_status returned HTTP {resp.status_code}: {resp.text[:200]}")
                return False
            response = resp.json()

            if response.get("success"):
                return True
            else:
                logger.error(
                    f"Failed to change user status on node {self.address}: {response.get('msg')}"
                )
                return False
        except Exception as e:
            logger.error(f"Error change user status on node {self.address}: {e}")
            return False

    def download_ovpn_client(self, name: str, timeout: int = 120) -> Response:
        api = f"{self.scheme}://{self.address}/sync/download/ovpn/{name}"
        try:
            response = requests.get(
                api,
                headers={**self.headers, "Accept": "application/x-openvpn-profile,text/plain,*/*"},
                timeout=timeout,
            )
            content_type = (response.headers.get("content-type") or "").lower()
            text_start = response.content[:512].decode("utf-8", errors="ignore").lstrip().lower()
            looks_like_ovpn = (
                response.content.lstrip().startswith(b"client")
                or b"<ca>" in response.content
                or b"remote " in response.content
            )
            if response.status_code == 200 and looks_like_ovpn and "text/html" not in content_type and not text_start.startswith("<html") and not text_start.startswith("<!doctype html"):
                return Response(
                    content=response.content,
                    media_type="application/x-openvpn-profile",
                    headers={
                        "Content-Disposition": f'attachment; filename="{name}.ovpn"',
                        "X-Content-Type-Options": "nosniff",
                    },
                )
            logger.error(
                "Node %s returned invalid OVPN response for %s: status=%s content-type=%s start=%r",
                self.address,
                name,
                response.status_code,
                content_type,
                text_start[:120],
            )
        except Exception as e:
            logger.error(f"Error downloading OVPN client from node {self.address}: {e}")
        return None

    def delete_user(self, name: str) -> bool:
        api = f"{self.scheme}://{self.address}/sync/user/{name}"
        try:
            response = requests.delete(
                api, headers=self.headers, timeout=25
            ).json()
            if response.get("success"):
                return True
            else:
                logger.error(
                    f"Failed to delete user on node {self.address}: {response.get('msg')}"
                )
                return False
        except Exception as e:
            logger.error(f"Error deleting user on node {self.address}: {e}")
            return False

    def set_user_limit(self, name: str, max_logins: int) -> bool:
        """Set the maximum simultaneous logins/devices for a user on the node.

        max_logins: 1 = single login, 0 = unlimited.
        """
        api = f"{self.scheme}://{self.address}/sync/user/limit"
        data = {"name": name, "max_logins": max_logins}
        try:
            resp = requests.put(
                api, headers=self.headers, json=data, timeout=60
            )
            if resp.status_code != 200:
                logger.error(f"Node {self.address} set_user_limit returned HTTP {resp.status_code}: {resp.text[:200]}")
                return False
            response = resp.json()
            if response.get("success"):
                return True
            else:
                logger.error(
                    f"Failed to set user limit on node {self.address}: {response.get('msg')}"
                )
                return False
        except Exception as e:
            logger.error(f"Error setting user limit on node {self.address}: {e}")
            return False

    def get_sessions(
        self,
        common_name: str | None = None,
        hours: int = 8,
        timeout: int | float = 15,
    ) -> dict | bool:
        api = f"{self.scheme}://{self.address}/sync/sessions"
        params = {"hours": hours}
        if common_name:
            params["common_name"] = common_name
        try:
            response = requests.get(api, headers=self.headers, params=params, timeout=timeout).json()
            if response.get("success"):
                return response.get("data") or {}
            logger.error(
                f"Failed to get sessions on node {self.address}: {response.get('msg')}"
            )
            return False
        except Exception as e:
            logger.error(f"Error when getting sessions on node {self.address}: {e}")
            return False

    def disconnect_user(self, name: str) -> dict | bool:
        api = f"{self.scheme}://{self.address}/sync/user/{name}/disconnect"
        try:
            response = requests.post(api, headers=self.headers, timeout=20).json()
            if response.get("success"):
                return response.get("data") or {}
            logger.error(
                f"Failed to disconnect user on node {self.address}: {response.get('msg')}"
            )
            return False
        except Exception as e:
            logger.error(f"Error disconnecting user on node {self.address}: {e}")
            return False

    def get_users_usage(self) ->dict | bool:
        api = f"{self.scheme}://{self.address}/sync/usage"
        try:
            response = requests.get(api, headers=self.headers, timeout=25).json()
            if response.get("success"):
                logger.info(f"get users usage on node {self.address}: {response.get('msg')}")
                return response.get("data")
            else:
                logger.error(
                    f"Failed to get users usage on node {self.address}: {response.get('msg')}"
                )
                return False
        except Exception as e:
            logger.error(f"Error when getting users usage on node {self.address}: {e}")
            return False