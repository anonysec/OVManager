from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, UTC
from uuid import uuid4

from backend.auth.hash import hash_password
from backend.db.exceptions import NotFoundError, ConflictError
from backend.logger import logger
from backend.schema._input import AdminCreate, CreateUser, UpdateUser, NodeCreate
from .models import User, Admin, Node, Settings
from cryptography.fernet import Fernet

try:
    from backend.config import config as panel_config
    _fernet = Fernet(panel_config.BOT_ENCRYPT_KEY.encode()) if panel_config.BOT_ENCRYPT_KEY else None
except Exception:
    _fernet = None

if _fernet is None:
    import logging
    logging.getLogger(__name__).warning(
        "BOT_ENCRYPT_KEY not set — bot tokens stored in plaintext at rest. "
        "Set BOT_ENCRYPT_KEY in .env for encryption: "
        "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )


def get_all_users(db: Session):
    users = db.query(User).all()
    return users


def get_users_by_admin(db: Session, admin_username: str):
    users = db.query(User).filter(User.owner == admin_username).all()
    return users


def get_admin_by_username(db: Session, username: str):
    admin = db.query(Admin).filter(Admin.username == username).first()
    return admin


def create_admin(db: Session, admin: AdminCreate):
    hashed_password = hash_password(admin.password)
    new_admin = Admin(username=admin.username, password=hashed_password)
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)
    return new_admin


def update_admin(db: Session, existing_admin: Admin, admin: AdminCreate):
    existing_admin.password = hash_password(admin.password)
    existing_admin.telegram_id = admin.telegram_id
    existing_admin.username_prefix = admin.username_prefix

    db.commit()
    db.refresh(existing_admin)
    return existing_admin


def get_admin_by_telegram_id(db: Session, tg_id: int):
    return db.query(Admin).filter(Admin.telegram_id == tg_id).first()


def update_bot_config(db: Session, **kwargs):
    s = db.query(Settings).first()
    if not s:
        s = Settings(port=1194, protocol="tcp")
        db.add(s)
        db.flush()
    for k, v in kwargs.items():
        if v is None:
            continue
        if k == "bot_token":
            if not v:
                v = None  # clear token → NULL in DB
            elif _fernet is None:
                raise RuntimeError("BOT_ENCRYPT_KEY is required before saving a bot token")
            else:
                v = _fernet.encrypt(v.encode()).decode()
        if hasattr(s, k):
            setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


def get_bot_config(db: Session):
    s = db.query(Settings).first()
    if not s:
        return {"bot_configured": False, "bot_enabled": False}
    return {
        # Never return plaintext or ciphertext token material to the browser.
        "bot_configured": bool(s.bot_token),
        "bot_enabled": s.bot_enabled,
        "default_days": s.default_days,
        "default_traffic_gb": s.default_traffic_gb,
        "default_max_users": s.default_max_users,
        "owner_telegram_id": s.owner_telegram_id,
    }


def patch_admin_telegram_id(db: Session, username: str, tg_id: int | None):
    admin = db.query(Admin).filter(Admin.username == username).first()
    if not admin:
        raise NotFoundError("Admin", username)
    admin.telegram_id = tg_id
    db.commit()
    db.refresh(admin)
    return admin


def get_user_by_name(db: Session, name: str):
    user = db.query(User).filter(User.name == name).first()
    if user:
        return user
    return None


def get_user_by_uuid(db: Session, uuid: str):
    user = db.query(User).filter(User.uuid == uuid).first()
    if user:
        return user
    return None


def create_user(db: Session, request: CreateUser, owner: str):
    username = request.name.replace(" ", "_")

    new_user = User(
        name=username,
        expiry_date=request.expiry_date,
        total=request.total,
        max_logins=request.max_logins,
        owner=owner,
        uuid=str(uuid4()),
    )

    db.add(new_user)
    try:
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise ConflictError("User", "name", username)
    logger.info("user created successfully: %s", request.name)
    return new_user


def update_user(db: Session, uuid: str, request: UpdateUser):
    user = db.query(User).filter(User.uuid == uuid).first()
    if not user:
        raise NotFoundError("User", uuid)
    
    used = user.used or 0
    # total=None means unlimited traffic, so it is never "exceeded".
    not_expired = (
        request.expiry_date >= datetime.now(UTC).date()
        if request.expiry_date
        else True
    )
    has_traffic = request.total is None or request.total > used
    # Manual status (from the edit modal checkbox) wins, but expiry/traffic
    # violations still force-disable: an expired or out-of-traffic account
    # must never be active even if the admin flipped the switch on.
    requested_status = user.is_active if request.status is None else bool(request.status)
    user.is_active = requested_status and not_expired and has_traffic
    user.expiry_date = request.expiry_date
    user.total = request.total
    if request.max_logins is not None:
        user.max_logins = request.max_logins

    db.commit()
    db.refresh(user)
    return {"detail": "User updated successfully"}


def change_user_status(db: Session, uuid: str, status: bool) -> bool:
    user = db.query(User).filter(User.uuid == uuid).first()
    if not user:
        logger.error("change_user_status: user not found for uuid=%s", uuid)
        return False
    try:
        user.is_active = status
        db.commit()
        db.refresh(user)
        return True
    except Exception as e:
        logger.error("Error changing status for user %s on db: %s", user.name, e)
        return False

def reset_user_usage(db: Session, uuid: str) -> bool:
    user = db.query(User).filter(User.uuid == uuid).first()
    if not user:
        return False

    user.used = 0
    # Reset the per-node baselines too, so the next sync starts counting from
    # the nodes' current cumulative values instead of producing a huge delta.
    user.last_node_usage = 0
    user.node_usage = "{}"
    db.commit()
    return True

def get_expired_users(db: Session):
    return (
        db.query(User)
        .filter(User.expiry_date < datetime.now(UTC).date(), User.is_active == True)
        .all()
    )


def get_users_exceeded_traffic(db: Session):
    # Exclude users with NULL total (unlimited traffic)
    return (
        db.query(User)
        .filter(User.total.isnot(None), User.used > User.total, User.is_active == True)
        .all()
    )


def delete_user(db: Session, name: str):
    user = db.query(User).filter(User.name == name).first()
    if not user:
        raise NotFoundError("User", name)

    db.delete(user)
    db.commit()


# admins crud
def get_all_admins(db: Session):
    admins = db.query(Admin).all()
    return admins


def it_is_admin(db: Session, username: str):
    """Return the Admin object if found, else None."""
    return db.query(Admin).filter(Admin.username == username).first()


def delete_admin(db: Session, admin: Admin):
    db.delete(admin)
    db.commit()
    return True


# nodes crud
def get_all_nodes(db: Session):
    nodes = db.query(Node).all()
    return nodes


def get_active_nodes(db: Session):
    """Return only nodes with status=True."""
    return db.query(Node).filter(Node.status == True).all()  # noqa: E712


def get_node_by_address(db: Session, address: str):
    return db.query(Node).filter(Node.address == address).first()


def get_node_by_id(db: Session, id: int):
    return db.query(Node).filter(Node.id == id).first()


def get_node_by_name(db: Session, name: str):
    return db.query(Node).filter(Node.name == name).first()


def create_node(db: Session, request: NodeCreate, geolocation: dict = None):
    new_node = Node(
        name=request.name,
        address=request.address,
        tunnel_address=request.tunnel_address,
        ovpn_port=request.ovpn_port,
        protocol=request.protocol,
        port=request.port,
        key=request.key,
        status=request.status,
        use_tls=request.use_tls,
        country_code=geolocation.get("country_code") if geolocation else None,
        latitude=geolocation.get("latitude") if geolocation else None,
        longitude=geolocation.get("longitude") if geolocation else None,
    )

    db.add(new_node)
    db.commit()
    db.refresh(new_node)
    return new_node


def update_node(db: Session, node_id: int, request: NodeCreate, geolocation: dict = None):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise NotFoundError("Node", str(node_id))

    node.name = request.name
    node.address = request.address
    node.tunnel_address = request.tunnel_address
    node.ovpn_port = request.ovpn_port
    node.protocol = request.protocol
    node.port = request.port
    if geolocation:
        node.country_code = geolocation.get("country_code")
        node.latitude = geolocation.get("latitude")
        node.longitude = geolocation.get("longitude")
    node.status = request.status
    node.use_tls = request.use_tls

    # Only overwrite API key if a non-empty value is provided
    if request.key and request.key.strip():
        node.key = request.key

    db.commit()
    db.refresh(node)
    return node


def delete_node(db: Session, id: int):
    node = db.query(Node).filter(Node.id == id).first()
    if not node:
        raise NotFoundError("Node", str(id))
    db.delete(node)
    db.commit()
    return {"detail": "Node deleted successfully"}


# settings crud
def get_settings(db: Session):
    settings = db.query(Settings).first()
    if not settings:
        settings = Settings(port=1194)
        settings.protocol = "tcp"
        db.add(settings)
        db.commit()
        db.refresh(settings)

    return settings


def update_setting_timezone(db: Session, timezone: str):
    settings = db.query(Settings).first()
    if not settings:
        settings = Settings(port=1194)
        settings.protocol = "tcp"
        db.add(settings)
        db.commit()
        db.refresh(settings)
    settings.timezone = timezone
    db.commit()
    return settings
