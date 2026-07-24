import requests
from fastapi.responses import Response
from backend.logger import logger

# Default timeouts (seconds) for node API calls. Prevents the panel from
# hanging indefinitely on an unreachable or slow node.
DEFAULT_TIMEOUT = 10
DEFAULT_LONG_TIMEOUT = 30
CREATE_USER_TIMEOUT = 180
DOWNLOAD_OVPN_TIMEOUT = 120


class NodeRequests:
    """Handles requests to the OVNode API.

    The node uses the panel's UUID (or simple ID) as the primary key.
    Display names are sent as optional metadata.

    TLS enforcement: when `use_tls=True`, all requests use HTTPS. The panel
    should set `use_tls=True` for any node that is not on a trusted local
    network. The node itself serves HTTP; TLS termination is expected at a
    reverse proxy (nginx/caddy) in front of the node container.
    """

    def __init__(
        self,
        address: str,
        port: int,
        api_key: str,
        tunnel_address: str = "ovpanel.com",
        protocol: str = "tcp",
        ovpn_port: int = 1194,
        set_new_setting: bool = False,
        use_tls: bool = False,
    ):
        self.address = f"{address}:{port}"
        self.headers = {"key": api_key}
        self.tunnel_address = tunnel_address
        self.protocol = protocol
        self.ovpn_port = ovpn_port
        self.set_new_setting = set_new_setting
        self.use_tls = use_tls
        self.scheme = "https" if use_tls else "http"

    def _url(self, path: str) -> str:
        return f"{self.scheme}://{self.address}{path}"

    def _parse_version(self, v: str) -> tuple:
        """Parse a version string like '1.5.0' into a comparable tuple."""
        try:
            return tuple(int(x) for x in v.split("."))
        except (ValueError, AttributeError):
            return (0, 0, 0)

    def check_node(self) -> bool:
        """Checks the node status and sets new settings if necessary.

        Returns True if the node is reachable and the version is compatible.
        """
        api = self._url("/sync/status")
        try:
            data = {
                "tunnel_address": self.tunnel_address,
                "protocol": self.protocol,
                "ovpn_port": self.ovpn_port,
                "set_new_setting": self.set_new_setting,
            }
            resp = requests.get(api, headers=self.headers, json=data, timeout=DEFAULT_TIMEOUT)
            if resp.status_code != 200:
                logger.error(f"Node {self.address} returned {resp.status_code}")
                return False
            response = resp.json()
            if response.get("success"):
                node_data = response.get("data") or {}
                node_version = node_data.get("version", "0.0.0")
                # Compatible: node version >= 1.5.0 (UUID-based API)
                if self._parse_version(node_version) < (1, 5, 0):
                    logger.warning(
                        f"Node {self.address} version {node_version} is too old. "
                        "Minimum required: 1.5.0"
                    )
                    return False
                return True
            else:
                logger.error(f"Node {self.address} is not reachable: {response.get('msg')}")
                return False
        except Exception as e:
            logger.error(f"Error checking node {self.address}: {e}")
            return False

    def get_node_info(self, timeout: int | float = DEFAULT_TIMEOUT) -> dict:
        api = self._url("/sync/status")
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

    def create_user(self, display_name: str, max_logins: int = 1, uid: str = None) -> bool:
        """Create a user on the node.

        `uid` is the panel UUID (primary key). `display_name` is optional metadata.
        """
        api = self._url("/sync/user")
        data = {"name": display_name, "max_logins": max_logins}
        if uid:
            data["id"] = uid
        try:
            resp = requests.post(
                api, headers=self.headers, json=data, timeout=CREATE_USER_TIMEOUT
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

    def change_user_status(self, display_name, status, max_logins: int | None = None, uid: str = None):
        """Change user status on the node.

        `uid` is the panel UUID (primary key). `display_name` is optional metadata.
        """
        api = self._url("/sync/user")
        try:
            data = {"name": display_name, "status": "activate" if status else "deactivate"}
            if uid:
                data["id"] = uid
            if max_logins is not None:
                data["max_logins"] = max_logins
            resp = requests.put(
                api, headers=self.headers, json=data, timeout=DEFAULT_LONG_TIMEOUT
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

    def download_ovpn_client(self, uid: str, timeout: int = DOWNLOAD_OVPN_TIMEOUT) -> Response:
        """Download the .ovpn config for a user identified by their panel UUID."""
        api = self._url(f"/sync/download/ovpn/{uid}")
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
                        "Content-Disposition": f'attachment; filename="{uid}.ovpn"',
                        "X-Content-Type-Options": "nosniff",
                    },
                )
            logger.error(
                "Node %s returned invalid OVPN response for %s: status=%s content-type=%s start=%r",
                self.address,
                uid,
                response.status_code,
                content_type,
                text_start[:120],
            )
        except Exception as e:
            logger.error(f"Error downloading OVPN client from node {self.address}: {e}")
        return None

    def delete_user(self, uid: str) -> bool:
        """Delete a user on the node by their panel UUID."""
        api = self._url(f"/sync/user/{uid}")
        try:
            response = requests.delete(
                api, headers=self.headers, timeout=DEFAULT_TIMEOUT
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

    def set_user_limit(self, uid: str, max_logins: int) -> bool:
        """Set the maximum simultaneous logins/devices for a user on the node.

        `uid` is the panel UUID. max_logins: 1 = single login, 0 = unlimited.
        """
        api = self._url("/sync/user/limit")
        data = {"id": uid, "max_logins": max_logins}
        try:
            resp = requests.put(
                api, headers=self.headers, json=data, timeout=DEFAULT_LONG_TIMEOUT
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
        timeout: int | float = DEFAULT_LONG_TIMEOUT,
    ) -> dict | bool:
        api = self._url("/sync/sessions")
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

    def disconnect_user(self, uid: str) -> dict | bool:
        """Disconnect a user on the node by their panel UUID."""
        api = self._url(f"/sync/user/{uid}/disconnect")
        try:
            response = requests.post(api, headers=self.headers, timeout=DEFAULT_TIMEOUT).json()
            if response.get("success"):
                return response.get("data") or {}
            logger.error(
                f"Failed to disconnect user on node {self.address}: {response.get('msg')}"
            )
            return False
        except Exception as e:
            logger.error(f"Error disconnecting user on node {self.address}: {e}")
            return False

    def get_users_usage(self) -> dict | bool:
        api = self._url("/sync/usage")
        try:
            response = requests.get(api, headers=self.headers, timeout=DEFAULT_LONG_TIMEOUT).json()
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