from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.db.engine import get_db
from backend.operations.audit import recent_events
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/activity", tags=["Activity"])


@router.get("/", response_model=ResponseModel)
async def get_activity(limit: int = 100, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    return ResponseModel(success=True, msg="Activity retrieved", data=recent_events(db, limit=limit))
