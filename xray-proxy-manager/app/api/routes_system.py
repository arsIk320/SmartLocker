from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ServiceStatus
from app.services.health import system_health


router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status", response_model=ServiceStatus)
def get_status(db: Session = Depends(get_db)):
    return ServiceStatus(**system_health(db))
