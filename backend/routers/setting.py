from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.db.engine import get_db
from backend.db import crud
from backend.auth.auth import get_current_user
from backend.operations.server_info import get_server_info
from backend.schema.output import Settings, ServerInfo, ResponseModel
from backend.config import config
from backend.version import __version__

router = APIRouter(prefix="/server", tags=["Panel Settings"])


@router.get("/settings/", response_model=ResponseModel, include_in_schema=False)
@router.get("/settings", response_model=ResponseModel)
async def get_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    urlpath = (config.URLPATH or "").strip("/")
    subscription_prefix = (
        config.SUBSCRIPTION_URL_PREFIX.rstrip("/") + "/"
        if config.SUBSCRIPTION_URL_PREFIX
        else str(request.base_url).rstrip("/") + (f"/{urlpath}/" if urlpath else "/")
    )
    db_settings = crud.get_settings(db)
    settings = Settings(
        subscription_path=config.SUBSCRIPTION_PATH.strip("/"),
        subscription_url_prefix=subscription_prefix,
        timezone=getattr(db_settings, "timezone", "UTC") or "UTC",
        panel_version=__version__,
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


@router.put("/settings/timezone", response_model=ResponseModel)
async def update_timezone(
    payload: TimezoneUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    tz = (payload.timezone or "UTC").strip() or "UTC"
    crud.update_setting_timezone(db, tz)
    return ResponseModel(success=True, msg="Timezone updated", data={"timezone": tz})


@router.put("/settings/subscription", response_model=ResponseModel)
async def update_subscription(
    payload: SubscriptionUpdate,
    user: str = Depends(get_current_user),
):
    if payload.subscription_url_prefix is not None:
        config.SUBSCRIPTION_URL_PREFIX = payload.subscription_url_prefix.strip()
    if payload.subscription_path is not None:
        config.SUBSCRIPTION_PATH = payload.subscription_path.strip()
    return ResponseModel(
        success=True,
        msg="Subscription link settings updated",
        data={
            "subscription_url_prefix": config.SUBSCRIPTION_URL_PREFIX,
            "subscription_path": config.SUBSCRIPTION_PATH,
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
