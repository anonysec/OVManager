import asyncio
import logging
import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.authz import require_owner
from backend.config import config
from backend.db import crud
from backend.db.engine import get_db
from backend.operations.observability.server_info import get_server_info
from backend.schema import ResponseModel, ServerInfo, Settings
from backend.urlpath import get_urlpath as _get_urlpath
from backend.urlpath import set_urlpath as _set_urlpath
from backend.version import __version__

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/server", tags=["Panel Settings"])

_AUTO_BACKUP_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_AUTO_BACKUP_KEEP_MIN = 1
_AUTO_BACKUP_KEEP_MAX = 500
_AUTO_BACKUP_FIELDS = frozenset({"auto_backup_enabled", "auto_backup_time", "auto_backup_keep"})
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
# Subscription page profile (D1): only http(s) links reach clients, and the
# two free-text fields are capped so a banner cannot swallow the page.
_SUB_SUPPORT_RE = re.compile(r"^https?://", re.IGNORECASE)
_SUB_TITLE_MAX = 64
_SUB_ANNOUNCE_MAX = 500
_SUB_UPDATE_HOURS_MIN = 1
_SUB_UPDATE_HOURS_MAX = 168
# Threshold bounds: days-left covers a year, percentages are percentages.
_THRESHOLD_BOUNDS = (("alert_days_left", 0, 365), ("alert_usage_pct", 1, 100), ("alert_cpu_pct", 1, 100))


def _threshold_data(db_settings) -> dict:
    """The threshold alert keys as served to the Settings UI.

    A stored ``0`` (alert only for today) is a real value, so missing and
    invalid are told apart by type rather than by truthiness.
    """

    def as_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return {
        "alert_days_left": as_int(getattr(db_settings, "alert_days_left", None), 3),
        "alert_usage_enabled": bool(getattr(db_settings, "alert_usage_enabled", True)),
        "alert_usage_pct": as_int(getattr(db_settings, "alert_usage_pct", None), 80),
        "alert_cpu_enabled": bool(getattr(db_settings, "alert_cpu_enabled", True)),
        "alert_cpu_pct": as_int(getattr(db_settings, "alert_cpu_pct", None), 85),
    }


@router.get("/settings/", response_model=ResponseModel, include_in_schema=False)
@router.get("/settings", response_model=ResponseModel)
async def get_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_owner),
):
    db_settings = crud.get_settings(db)
    urlpath = _get_urlpath()

    db_prefix = getattr(db_settings, "subscription_url_prefix", None)
    sub_prefix_source = db_prefix if db_prefix else config.SUBSCRIPTION_URL_PREFIX
    public_base = (config.PUBLIC_URL or str(request.base_url)).rstrip("/")
    subscription_prefix = (
        sub_prefix_source.rstrip("/") + "/" if sub_prefix_source else public_base + (f"/{urlpath}/" if urlpath else "/")
    )

    db_sub_path = getattr(db_settings, "subscription_path", None) or "sub"
    sub_path = db_sub_path if db_sub_path else config.SUBSCRIPTION_PATH

    settings = Settings(
        subscription_path=sub_path.strip("/"),
        subscription_url_prefix=subscription_prefix,
        timezone=getattr(db_settings, "timezone", "UTC") or "UTC",
        panel_version=__version__,
        bot_token=None,
        bot_configured=bool(getattr(db_settings, "bot_token", None)),
        bot_enabled=bool(getattr(db_settings, "bot_enabled", False)),
        default_days=getattr(db_settings, "default_days", 30) or 30,
        default_traffic_gb=getattr(db_settings, "default_traffic_gb", 100) or 100,
        default_max_users=getattr(db_settings, "default_max_users", 1) or 1,
        owner_telegram_id=getattr(db_settings, "owner_telegram_id", None) or None,
        urlpath=urlpath,
        panel_domain=getattr(db_settings, "panel_domain", None) or None,
        sub_profile_title=getattr(db_settings, "sub_profile_title", None) or "",
        sub_support_url=getattr(db_settings, "sub_support_url", None) or "",
        sub_announce=getattr(db_settings, "sub_announce", None) or "",
        sub_update_interval_hours=int(getattr(db_settings, "sub_update_interval_hours", 12) or 12),
    )
    data = settings.model_dump()
    data["notify_expiry"] = bool(getattr(db_settings, "notify_expiry", True))
    data["notify_traffic"] = bool(getattr(db_settings, "notify_traffic", True))
    data["notify_node_down"] = bool(getattr(db_settings, "notify_node_down", True))
    data.update(_threshold_data(db_settings))
    data["auto_backup_enabled"] = bool(getattr(db_settings, "auto_backup_enabled", False))
    data["auto_backup_time"] = getattr(db_settings, "auto_backup_time", None) or "03:30"
    data["auto_backup_keep"] = int(getattr(db_settings, "auto_backup_keep", 50) or 50)
    data["offsite_backup_target"] = getattr(db_settings, "offsite_backup_target", None) or ""
    data["telegram_backup_enabled"] = bool(getattr(db_settings, "telegram_backup_enabled", False))
    data["telegram_backup_available"] = bool(getattr(db_settings, "bot_token", None))
    return ResponseModel(
        success=True,
        msg="Settings retrieved successfully",
        data=data,
    )


class TimezoneUpdate(BaseModel):
    timezone: str


class SubscriptionUpdate(BaseModel):
    subscription_url_prefix: str | None = None
    subscription_path: str | None = None
    sub_profile_title: str | None = None
    sub_support_url: str | None = None
    sub_announce: str | None = None
    sub_update_interval_hours: int | None = None


class BotConfigUpdate(BaseModel):
    bot_token: str | None = None
    bot_enabled: bool | None = None
    default_days: int | None = None
    default_traffic_gb: int | None = None
    default_max_users: int | None = None
    owner_telegram_id: int | None = None
    notify_expiry: bool | None = None
    notify_traffic: bool | None = None
    notify_node_down: bool | None = None
    alert_days_left: int | None = None
    alert_usage_enabled: bool | None = None
    alert_usage_pct: int | None = None
    alert_cpu_enabled: bool | None = None
    alert_cpu_pct: int | None = None
    auto_backup_enabled: bool | None = None
    auto_backup_time: str | None = None
    auto_backup_keep: int | None = None
    offsite_backup_target: str | None = None
    telegram_backup_enabled: bool | None = None


class URLPathUpdate(BaseModel):
    urlpath: str = Field(default="", description="Panel URL path prefix. Empty = root. Alphanumeric, dashes, underscores only.")


class DomainUpdate(BaseModel):
    panel_domain: str | None = None


@router.put("/settings/timezone", response_model=ResponseModel)
async def update_timezone(
    payload: TimezoneUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    tz = (payload.timezone or "UTC").strip() or "UTC"
    from zoneinfo import available_timezones

    if tz != "UTC" and tz not in available_timezones():
        return ResponseModel(success=False, msg=f"Invalid timezone: {tz}", data=None)
    crud.update_setting_timezone(db, tz)
    return ResponseModel(success=True, msg="Timezone updated", data={"timezone": tz})


@router.put("/settings/subscription", response_model=ResponseModel)
async def update_subscription(
    payload: SubscriptionUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    # Validate the whole payload before anything is written, so a rejected
    # value can never leave a half-applied row behind.
    if payload.sub_profile_title is not None and len(payload.sub_profile_title.strip()) > _SUB_TITLE_MAX:
        return ResponseModel(
            success=False,
            msg=f"Subscription title must be at most {_SUB_TITLE_MAX} characters",
            data=None,
        )
    if payload.sub_announce is not None and len(payload.sub_announce.strip()) > _SUB_ANNOUNCE_MAX:
        return ResponseModel(
            success=False,
            msg=f"Announcement must be at most {_SUB_ANNOUNCE_MAX} characters",
            data=None,
        )
    if payload.sub_support_url is not None:
        support_url = payload.sub_support_url.strip()
        if support_url and not _SUB_SUPPORT_RE.match(support_url):
            return ResponseModel(
                success=False,
                msg="Support link must start with http:// or https://",
                data=None,
            )
    if payload.sub_update_interval_hours is not None and not (
        _SUB_UPDATE_HOURS_MIN <= payload.sub_update_interval_hours <= _SUB_UPDATE_HOURS_MAX
    ):
        return ResponseModel(
            success=False,
            msg=f"sub_update_interval_hours must be between {_SUB_UPDATE_HOURS_MIN} and {_SUB_UPDATE_HOURS_MAX}",
            data=None,
        )

    db_settings = crud.get_settings(db)
    if payload.subscription_url_prefix is not None:
        db_settings.subscription_url_prefix = payload.subscription_url_prefix.strip()
    if payload.subscription_path is not None:
        requested_path = payload.subscription_path.strip("/")
        if not requested_path or requested_path != config.SUBSCRIPTION_PATH.strip("/"):
            return ResponseModel(
                success=False,
                msg="Subscription path changes require a restart and route configuration update",
                data={"subscription_path": config.SUBSCRIPTION_PATH.strip("/")},
            )
        db_settings.subscription_path = requested_path

    if payload.sub_profile_title is not None:
        db_settings.sub_profile_title = payload.sub_profile_title.strip()
    if payload.sub_support_url is not None:
        db_settings.sub_support_url = payload.sub_support_url.strip()
    if payload.sub_announce is not None:
        db_settings.sub_announce = payload.sub_announce.strip()
    if payload.sub_update_interval_hours is not None:
        db_settings.sub_update_interval_hours = payload.sub_update_interval_hours
    db.commit()
    return ResponseModel(
        success=True,
        msg="Subscription link settings updated",
        data={
            "subscription_url_prefix": db_settings.subscription_url_prefix or "",
            "subscription_path": db_settings.subscription_path,
            "sub_profile_title": db_settings.sub_profile_title or "",
            "sub_support_url": db_settings.sub_support_url or "",
            "sub_announce": db_settings.sub_announce or "",
            "sub_update_interval_hours": db_settings.sub_update_interval_hours,
        },
    )


@router.put("/settings/domain", response_model=ResponseModel)
async def update_panel_domain(
    payload: DomainUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Set the domain clients use in generated .ovpn files.

    Empty clears it and downloads fall back to node IPs. A bare hostname only —
    scheme, port and path belong in the DNS record, not here.
    """
    domain = (payload.panel_domain or "").strip().lower().rstrip(".")
    if domain and not _DOMAIN_RE.match(domain):
        return ResponseModel(
            success=False,
            msg="Enter a bare domain name (e.g. vpn.example.com) — no scheme, port or path.",
            data=None,
        )
    db_settings = crud.get_settings(db)
    db_settings.panel_domain = domain or None
    db.commit()
    return ResponseModel(
        success=True,
        msg="VPN domain updated" if domain else "VPN domain cleared — .ovpn files will use node IPs",
        data={"panel_domain": db_settings.panel_domain or ""},
    )


@router.put("/settings/bot", response_model=ResponseModel)
async def update_bot_config(
    payload: BotConfigUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    if payload.auto_backup_time is not None and not _AUTO_BACKUP_TIME_RE.match(payload.auto_backup_time):
        return ResponseModel(
            success=False,
            msg="auto_backup_time must be a valid 24-hour time in HH:MM format",
            data=None,
        )
    if payload.auto_backup_keep is not None and not (_AUTO_BACKUP_KEEP_MIN <= payload.auto_backup_keep <= _AUTO_BACKUP_KEEP_MAX):
        return ResponseModel(
            success=False,
            msg=f"auto_backup_keep must be between {_AUTO_BACKUP_KEEP_MIN} and {_AUTO_BACKUP_KEEP_MAX}",
            data=None,
        )
    if payload.offsite_backup_target is not None and payload.offsite_backup_target.strip():
        from backend.operations.backup.offsite import InvalidTarget, parse_target

        try:
            parse_target(payload.offsite_backup_target)
        except InvalidTarget as exc:
            return ResponseModel(success=False, msg=str(exc), data=None)

    for name, low, high in _THRESHOLD_BOUNDS:
        value = getattr(payload, name, None)
        if value is not None and not (low <= value <= high):
            return ResponseModel(success=False, msg=f"{name} must be between {low} and {high}", data=None)

    if payload.telegram_backup_enabled:
        current = crud.get_settings(db)
        token = payload.bot_token or getattr(current, "bot_token", None)
        owner_id = payload.owner_telegram_id or getattr(current, "owner_telegram_id", None)
        if not token or not owner_id:
            return ResponseModel(
                success=False,
                msg="Configure the Telegram bot token and owner chat before enabling Telegram backups",
                data=None,
            )

    kwargs = payload.model_dump(exclude_unset=True)
    try:
        crud.update_bot_config(db, **kwargs)
    except RuntimeError as exc:
        return ResponseModel(
            success=False,
            msg=str(exc) + ". Set BOT_ENCRYPT_KEY in your .env file before saving a bot token.",
            data=None,
        )
    data = crud.get_bot_config(db)
    db_settings = crud.get_settings(db)
    data["notify_expiry"] = bool(getattr(db_settings, "notify_expiry", True))
    data["notify_traffic"] = bool(getattr(db_settings, "notify_traffic", True))
    data["notify_node_down"] = bool(getattr(db_settings, "notify_node_down", True))
    data.update(_threshold_data(db_settings))
    data["auto_backup_enabled"] = bool(getattr(db_settings, "auto_backup_enabled", False))
    data["auto_backup_time"] = getattr(db_settings, "auto_backup_time", None) or "03:30"
    data["auto_backup_keep"] = int(getattr(db_settings, "auto_backup_keep", 50) or 50)
    data["offsite_backup_target"] = getattr(db_settings, "offsite_backup_target", None) or ""
    data["telegram_backup_enabled"] = bool(getattr(db_settings, "telegram_backup_enabled", False))
    data["telegram_backup_available"] = bool(getattr(db_settings, "bot_token", None))

    if _AUTO_BACKUP_FIELDS & payload.model_fields_set:
        try:
            from backend.app import reschedule_auto_backup

            reschedule_auto_backup()
        except Exception:
            logger.exception("Could not reschedule the automatic backup job")

    return ResponseModel(
        success=True,
        msg="Bot config updated",
        data=data,
    )


class AlertTestUpdate(BaseModel):
    channel: str = "telegram"


@router.post("/alerts/test", response_model=ResponseModel)
async def test_alert_channel(
    payload: AlertTestUpdate | None = None,
    user: str = Depends(require_owner),
):
    """Send one test message on a notification channel.

    Telegram is the only channel in this release; anything else is refused
    rather than silently ignored. The send runs off the event loop because
    ``send_telegram`` blocks on HTTP.
    """
    channel = ((payload.channel if payload else None) or "telegram").strip().lower()
    if channel != "telegram":
        return ResponseModel(success=False, msg=f"Unsupported alert channel: {channel}", data=None)

    from backend.operations.observability import notifier

    sent = await asyncio.to_thread(
        notifier.send_telegram,
        "OVManager test alert — Telegram notifications are wired up.",
    )
    return ResponseModel(
        success=bool(sent),
        msg="Test alert sent to Telegram"
        if sent
        else "Telegram test failed — check the bot token, owner chat ID and that the bot is enabled",
        data={"channel": "telegram", "sent": bool(sent)},
    )


@router.put("/settings/urlpath", response_model=ResponseModel)
async def update_urlpath(
    payload: URLPathUpdate,
    user: dict = Depends(require_owner),
):
    """Change the panel URL path prefix at runtime.

    - Empty string → panel served at root (/)
    - Non-empty → panel served only at /<urlpath>/...
    - When set, root and other paths return empty response (security)
    - Takes effect within 5 seconds (cache TTL) — no restart needed
    """
    from backend.validation import validate_urlpath

    value = (payload.urlpath or "").strip("/")

    if not validate_urlpath(value):
        return ResponseModel(
            success=False,
            msg="URL path must contain only letters, numbers, dashes, and underscores",
            data=None,
        )

    from backend.urlpath import reserved_prefixes

    if value and value.lower() in reserved_prefixes():
        return ResponseModel(
            success=False,
            msg=f"'{value}' is reserved and cannot be used as the panel URL path",
            data=None,
        )

    try:
        new_value = _set_urlpath(value)
    except RuntimeError as exc:
        return ResponseModel(success=False, msg=str(exc), data=None)

    return ResponseModel(
        success=True,
        msg="URL path updated — panel moved to the new path immediately."
        if new_value
        else "URL path cleared — panel now served at root.",
        data={
            "urlpath": new_value,
            "panel_url": f"/{new_value}" if new_value else "/",
        },
    )


@router.get(
    "/info",
    response_model=ResponseModel,
    description="Get server information (cpu, memory, ...)",
)
async def get_server_information(user: dict = Depends(require_owner)):
    result = await get_server_info()
    return ResponseModel(
        success=True,
        msg="Server information retrieved successfully",
        data=ServerInfo.model_validate(result),
    )
