from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from backend.db.engine import get_db
from backend.db import crud
from backend.auth.auth import get_current_user
from backend.auth.authz import require_main_admin
from backend.operations.server_info import get_server_info
from backend.schema.output import Settings, ServerInfo, ResponseModel
from backend.config import config
from backend.version import __version__
from backend.urlpath import set_urlpath as _set_urlpath, get_urlpath as _get_urlpath

router = APIRouter(prefix="/server", tags=["Panel Settings"])


@router.get("/settings/", response_model=ResponseModel, include_in_schema=False)
@router.get("/settings", response_model=ResponseModel)
async def get_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    db_settings = crud.get_settings(db)
    urlpath = _get_urlpath()

    # Subscription prefix: DB-persisted > env config > request base URL
    db_prefix = getattr(db_settings, "subscription_url_prefix", None)
    sub_prefix_source = db_prefix if db_prefix else config.SUBSCRIPTION_URL_PREFIX
    public_base = (config.PUBLIC_URL or str(request.base_url)).rstrip("/")
    subscription_prefix = (
        sub_prefix_source.rstrip("/") + "/"
        if sub_prefix_source
        else public_base + (f"/{urlpath}/" if urlpath else "/")
    )

    # Subscription path: DB-persisted > env config
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
    )
    return ResponseModel(
        success=True,
        msg="Settings retrieved successfully",
        data=settings,
    )


class TimezoneUpdate(BaseModel):
    timezone: str


class SubscriptionUpdate(BaseModel):
    subscription_url_prefix: str | None = None
    subscription_path: str | None = None


class BotConfigUpdate(BaseModel):
    bot_token: str | None = None
    bot_enabled: bool | None = None
    default_days: int | None = None
    default_traffic_gb: int | None = None
    default_max_users: int | None = None
    owner_telegram_id: int | None = None


class URLPathUpdate(BaseModel):
    urlpath: str = Field(default="", description="Panel URL path prefix. Empty = root. Alphanumeric, dashes, underscores only.")


@router.put("/settings/timezone", response_model=ResponseModel)
async def update_timezone(
    payload: TimezoneUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_main_admin),
):
    tz = (payload.timezone or "UTC").strip() or "UTC"
    # Validate IANA timezone name
    from zoneinfo import available_timezones
    if tz != "UTC" and tz not in available_timezones():
        return ResponseModel(success=False, msg=f"Invalid timezone: {tz}", data=None)
    crud.update_setting_timezone(db, tz)
    return ResponseModel(success=True, msg="Timezone updated", data={"timezone": tz})


@router.put("/settings/subscription", response_model=ResponseModel)
async def update_subscription(
    payload: SubscriptionUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_main_admin),
):
    # Persist to DB so settings survive restarts
    db_settings = crud.get_settings(db)
    if payload.subscription_url_prefix is not None:
        db_settings.subscription_url_prefix = payload.subscription_url_prefix.strip()
        config.SUBSCRIPTION_URL_PREFIX = payload.subscription_url_prefix.strip()
    if payload.subscription_path is not None:
        requested_path = payload.subscription_path.strip("/")
        if not requested_path or requested_path != config.SUBSCRIPTION_PATH.strip("/"):
            return ResponseModel(
                success=False,
                msg="Subscription path changes require a restart and route configuration update",
                data={"subscription_path": config.SUBSCRIPTION_PATH.strip("/")},
            )
        db_settings.subscription_path = requested_path
    db.commit()
    return ResponseModel(
        success=True,
        msg="Subscription link settings updated",
        data={
            "subscription_url_prefix": db_settings.subscription_url_prefix or "",
            "subscription_path": db_settings.subscription_path,
        },
    )


@router.put("/settings/bot", response_model=ResponseModel)
async def update_bot_config(
    payload: BotConfigUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_main_admin),
):
    kwargs = payload.model_dump(exclude_unset=True)
    crud.update_bot_config(db, **kwargs)
    return ResponseModel(
        success=True,
        msg="Bot config updated",
        data=crud.get_bot_config(db),
    )


@router.put("/settings/urlpath", response_model=ResponseModel)
async def update_urlpath(
    payload: URLPathUpdate,
    user: dict = Depends(require_main_admin),
):
    """Change the panel URL path prefix at runtime.

    - Empty string → panel served at root (/)
    - Non-empty → panel served only at /<urlpath>/...
    - When set, root and other paths return empty response (security)
    - Takes effect within 5 seconds (cache TTL) — no restart needed

    Only main_admin can change this.
    """
    import re

    value = (payload.urlpath or "").strip("/")

    # Validate: only allow safe characters (alphanumeric, dash, underscore)
    if value and not re.match(r'^[A-Za-z0-9_-]+$', value):
        return ResponseModel(
            success=False,
            msg="URL path must contain only letters, numbers, dashes, and underscores",
            data=None,
        )

    # Max length to prevent abuse
    if len(value) > 64:
        return ResponseModel(
            success=False,
            msg="URL path must be 64 characters or less",
            data=None,
        )

    try:
        new_value = _set_urlpath(value)
    except RuntimeError as exc:
        return ResponseModel(success=False, msg=str(exc), data=None)

    return ResponseModel(
        success=True,
        msg="URL path updated. Takes effect within 5 seconds." if new_value else "URL path cleared — panel now served at root.",
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
async def get_server_information(user: dict = Depends(get_current_user)):
    result = await get_server_info()
    return ResponseModel(
        success=True,
        msg="Server information retrieved successfully",
        data=ServerInfo.model_validate(result),
    )
