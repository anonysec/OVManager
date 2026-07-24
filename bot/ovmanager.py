import httpx
import logging
from bot.config import config

logger = logging.getLogger("ovmanager")
TIMEOUT = 30.0  # seconds for all HTTP calls to panel API

class OVManager:
    def __init__(self):
        self.base = config.api_url.rstrip("/") if config.api_url else ""

    async def _get(self, path: str):
        if not self.base:
            raise Exception("API URL not configured")
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(f"{self.base}/{path.lstrip('/')}")
            return r.json()

    async def _post(self, path: str, data: dict):
        if not self.base:
            raise Exception("API URL not configured")
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{self.base}/{path.lstrip('/')}", json=data)
            return r.json()

    async def _delete(self, path: str):
        if not self.base:
            raise Exception("API URL not configured")
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.delete(f"{self.base}/{path.lstrip('/')}")
            return r.json()

    async def _patch(self, path: str, data: dict):
        if not self.base:
            raise Exception("API URL not configured")
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.patch(f"{self.base}/{path.lstrip('/')}", json=data)
            return r.json()

    async def get_settings(self):
        return self._get_settings_from_db()

    def _get_settings_from_db(self) -> dict:
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            db = SessionLocal()
            try:
                s = db.query(models.Settings).first()
                if s:
                    return {
                        "bot_token": s.bot_token,
                        "bot_enabled": s.bot_enabled,
                        "default_days": s.default_days,
                        "default_traffic_gb": s.default_traffic_gb,
                        "default_max_users": s.default_max_users,
                        "owner_telegram_id": s.owner_telegram_id,
                    }
                return {}
            finally:
                db.close()
        except Exception as e:
            logger.error("DB error: %s", e)
            return {}

    async def get_admins(self):
        return self._get_admins_from_db()

    def _get_admins_from_db(self) -> list:
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            db = SessionLocal()
            try:
                admins = []
                for a in db.query(models.Admin).all():
                    admins.append({
                        "id": a.id,
                        "username": a.username,
                        "telegram_id": a.telegram_id,
                        "username_prefix": a.username_prefix,
                    })
                return admins
            finally:
                db.close()
        except Exception as e:
            logger.error("DB error: %s", e)
            return []

    async def get_status(self):
        return self._get_status_from_db()

    def _get_status_from_db(self):
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            from sqlalchemy import text
            db = SessionLocal()
            try:
                info = {}
                q = db.execute(text("SELECT COUNT(*) as total, SUM(used) as used FROM users"))
                r = q.fetchone()
                if r:
                    info["users"] = {"total": r.total or 0, "used": r.used or 0}
                q = db.execute(text("SELECT COUNT(*) as cnt FROM nodes"))
                r = q.fetchone()
                info["nodes"] = r.cnt if r else 0
                return {"status": "online", **info}
            finally:
                db.close()
        except Exception as e:
            logger.error("DB error: %s", e)
            return {"status": "online"}

    async def get_next_username(self):
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            db = SessionLocal()
            try:
                admin = db.query(models.Admin).filter(models.Admin.username_prefix.isnot(None)).first()
                if not admin or not admin.username_prefix:
                    return None
                prefix = admin.username_prefix
                users = db.query(models.User).all()
                max_num = 0
                for u in users:
                    if u.name and u.name.startswith(prefix):
                        try:
                            num = int(u.name[len(prefix):])
                            max_num = max(max_num, num)
                        except ValueError:
                            pass
                return f"{prefix}{max_num + 1}"
            finally:
                db.close()
        except Exception:
            return None

    async def get_users(self):
        return self._get_users_from_db()

    def _get_users_from_db(self) -> list:
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            db = SessionLocal()
            try:
                users = []
                for u in db.query(models.User).all():
                    user_dict = {k: getattr(u, k) for k in u.__table__.columns.keys()}
                    users.append(user_dict)
                return users
            finally:
                db.close()
        except Exception as e:
            logger.error("DB error: %s", e)
            return []

    async def get_user(self, username: str):
        users = self._get_users_from_db()
        for u in users:
            if u.get("name") == username:
                return u
        return {}

    async def create_user(self, name: str, days: int = 30, traffic_gb: int = 100, max_users: int = 1):
        return self._create_user_from_db(name, days, traffic_gb, max_users)

    def _create_user_from_db(self, name: str, days: int, traffic_gb: int, max_users: int):
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            from datetime import date, timedelta
            db = SessionLocal()
            try:
                username = name
                admin = db.query(models.Admin).filter(models.Admin.username_prefix.isnot(None)).first()
                if days == 0:
                    exp = date(2099, 12, 31)
                    days_str = "Unlimited"
                else:
                    exp = date.today() + timedelta(days=days)
                    days_str = f"{days}d"
                traffic_str = "Unlimited" if traffic_gb == 0 else f"{traffic_gb}GB"
                max_users_str = "Unlimited" if max_users == 0 else str(max_users)
                total_bytes = traffic_gb * 1073741824 if traffic_gb > 0 else None
                new_user = models.User(
                    name=username,
                    owner=admin.username if admin else "unknown",
                    expiry_date=exp,
                    total=total_bytes,
                    max_logins=max_users if max_users > 0 else 0,
                )
                db.add(new_user)
                db.commit()
                db.refresh(new_user)
                return {
                    "success": True,
                    "username": username,
                    "days": days_str,
                    "traffic": traffic_str,
                    "max_users": max_users_str,
                    "exp": exp,
                }
            except Exception as e:
                db.rollback()
                return {"success": False, "msg": str(e)}
            finally:
                db.close()
        except Exception as e:
            return {"success": False, "msg": str(e)}

    async def update_user(self, username: str, data: dict):
        return self._update_user_from_db(username, data)

    def _update_user_from_db(self, username: str, data: dict):
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            from sqlalchemy import update
            db = SessionLocal()
            try:
                stmt = update(models.User).where(models.User.name == username).values(**data)
                db.execute(stmt)
                db.commit()
                return {"success": True}
            except Exception as e:
                db.rollback()
                return {"success": False, "msg": str(e)}
            finally:
                db.close()
        except Exception as e:
            return {"success": False, "msg": str(e)}

    async def renew_user(self, name: str, days: int, traffic_gb: int, max_users: int):
        return self._renew_user_from_db(name, days, traffic_gb, max_users)

    def _renew_user_from_db(self, name: str, days: int, traffic_gb: int, max_users: int):
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            from datetime import date, timedelta
            db = SessionLocal()
            try:
                user = db.query(models.User).filter(models.User.name == name).first()
                if not user:
                    return {"success": False, "msg": "User not found"}
                if days == 0:
                    user.expiry_date = date(2099, 12, 31)
                else:
                    user.expiry_date = date.today() + timedelta(days=days)
                user.total = traffic_gb * 1073741824 if traffic_gb > 0 else None
                user.max_logins = max_users if max_users > 0 else 0
                user.is_active = True
                db.commit()
                return {"success": True, "expiry_date": str(user.expiry_date)}
            except Exception as e:
                db.rollback()
                return {"success": False, "msg": str(e)}
            finally:
                db.close()
        except Exception as e:
            return {"success": False, "msg": str(e)}

    async def toggle_user_status(self, name: str):
        return self._toggle_user_status_from_db(name)

    def _toggle_user_status_from_db(self, name: str):
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            db = SessionLocal()
            try:
                user = db.query(models.User).filter(models.User.name == name).first()
                if not user:
                    return {"success": False, "msg": "User not found"}
                user.is_active = not user.is_active
                db.commit()
                return {"success": True, "is_active": user.is_active}
            except Exception as e:
                db.rollback()
                return {"success": False, "msg": str(e)}
            finally:
                db.close()
        except Exception as e:
            return {"success": False, "msg": str(e)}

    async def delete_user(self, username: str):
        return self._delete_user_from_db(username)

    def _delete_user_from_db(self, username: str):
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            from sqlalchemy import delete
            db = SessionLocal()
            try:
                stmt = delete(models.User).where(models.User.name == username)
                db.execute(stmt)
                db.commit()
                return {"success": True}
            except Exception as e:
                db.rollback()
                return {"success": False, "msg": str(e)}
            finally:
                db.close()
        except Exception as e:
            return {"success": False, "msg": str(e)}

    async def get_nodes(self):
        return self._get_nodes_from_db()

    def _get_nodes_from_db(self):
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            db = SessionLocal()
            try:
                nodes = []
                for n in db.query(models.Node).all():
                    node_dict = {k: getattr(n, k) for k in n.__table__.columns.keys()}
                    nodes.append(node_dict)
                return nodes
            finally:
                db.close()
        except Exception as e:
            logger.error("DB error: %s", e)
            return []

    async def get_node(self, node_id: int):
        nodes = self._get_nodes_from_db()
        for n in nodes:
            if n.get("id") == node_id:
                return n
        return {}

    async def get_node_users(self, node_id: int):
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            db = SessionLocal()
            try:
                users = []
                for u in db.query(models.User).filter(models.User.node_id == node_id).all():
                    user_dict = {k: getattr(u, k) for k in u.__table__.columns.keys()}
                    users.append(user_dict)
                return users
            finally:
                db.close()
        except Exception as e:
            logger.error("DB error: %s", e)
            return []

    async def download_config(self, username: str, node_name: str):
        """Download .ovpn config via panel API. Returns file content str or None."""
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            from backend.node.task import download_ovpn_client_from_node
            db = SessionLocal()
            try:
                user = db.query(models.User).filter(models.User.name == username).first()
                if not user or not user.uuid:
                    return None
                node = db.query(models.Node).filter(models.Node.name == node_name).first()
                if not node:
                    return None
                resp = await download_ovpn_client_from_node(user.uuid, node.id, db)
                if resp and hasattr(resp, "body"):
                    raw = resp.body
                    text = raw.decode() if isinstance(raw, bytes) else raw
                    # Reject non-OVPN content (HTML error pages, etc.)
                    stripped = text.lstrip()[:200].lower()
                    if stripped.startswith("<") or "<html" in stripped or "<!doctype" in stripped:
                        return None
                    return text
                return None
            except Exception:
                return None
            finally:
                db.close()
        except Exception:
            return None

    async def get_sub_url(self, username: str) -> str | None:
        """Get the subscription URL for a user."""
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models
            from backend.config import config as panel_config
            import os
            db = SessionLocal()
            try:
                user = db.query(models.User).filter(models.User.name == username).first()
                if not user or not user.uuid:
                    return None
                # Priority: config.SUBSCRIPTION_URL_PREFIX > PUBLIC_URL env > panel base URL
                sub_prefix = getattr(panel_config, 'SUBSCRIPTION_URL_PREFIX', None) or ""
                if not sub_prefix:
                    sub_prefix = os.environ.get('PUBLIC_URL', '') or ""
                sub_path = getattr(panel_config, 'SUBSCRIPTION_PATH', None) or "sub"
                panel_url = self.base.rstrip("/") if self.base else ""
                if sub_prefix:
                    base = sub_prefix.rstrip("/")
                elif panel_url:
                    base = panel_url
                else:
                    return None
                return f"{base}/{sub_path}/{user.uuid}"
            except Exception:
                return None
            finally:
                db.close()
        except Exception:
            return None