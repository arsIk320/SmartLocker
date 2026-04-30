from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import DomainList
from app.services.xray import read_domains, sync_xray, write_domains


router = APIRouter(prefix="/api/domains", tags=["domains"])


@router.get("", response_model=DomainList)
def get_domains():
    return DomainList(domains=read_domains())


@router.put("", response_model=DomainList)
def put_domains(payload: DomainList, db: Session = Depends(get_db)):
    write_domains(payload.domains)
    sync_xray(db)
    return DomainList(domains=read_domains())
