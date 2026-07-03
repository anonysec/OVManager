from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.db.engine import get_db
from backend.operations.metrics import collect_metrics, history
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/history", response_model=ResponseModel)
async def metrics_history(hours: int = 24, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    return ResponseModel(success=True, msg="Metrics history", data=history(db, hours=hours))


@router.post("/collect", response_model=ResponseModel)
async def collect_now(user: dict = Depends(get_current_user)):
    await collect_metrics()
    return ResponseModel(success=True, msg="Metrics snapshot collected")
