from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.db.engine import get_db
from backend.node.task import clean_stale_sessions_all_nodes, login_health_summary, sync_all_user_limits
from backend.operations.audit import log_event
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


@router.get("/login-health", response_model=ResponseModel)
async def login_health(hours: int = 8, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    data = await login_health_summary(db, hours=hours)
    return ResponseModel(success=True, msg="Login health", data=data)


@router.post("/sync-limits", response_model=ResponseModel)
async def sync_limits(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    if user["type"] != "main_admin":
        return ResponseModel(success=False, msg="Unauthorized", data=None)
    data = await sync_all_user_limits(db)
    log_event(db, "maintenance.sync_limits", actor=user.get("username"), detail=f"{data.get('success')}/{data.get('total')} synced")
    return ResponseModel(success=True, msg="Login limits synced", data=data)


@router.post("/clean-stale", response_model=ResponseModel)
async def clean_stale(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    if user["type"] != "main_admin":
        return ResponseModel(success=False, msg="Unauthorized", data=None)
    data = await clean_stale_sessions_all_nodes(db)
    log_event(db, "maintenance.clean_stale", actor=user.get("username"), detail=f"removed={data.get('removed_total')}")
    return ResponseModel(success=True, msg="Stale sessions cleaned", data=data)
