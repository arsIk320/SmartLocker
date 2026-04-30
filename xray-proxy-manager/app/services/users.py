import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProxyUser


def list_users(db: Session) -> list[ProxyUser]:
    return list(db.scalars(select(ProxyUser).order_by(ProxyUser.created_at.asc())))


def create_user(db: Session, name: str) -> ProxyUser:
    existing = db.scalar(select(ProxyUser).where(ProxyUser.name == name))
    if existing:
        raise ValueError(f"user '{name}' already exists")

    user = ProxyUser(uuid=str(uuid.uuid4()), name=name.strip(), enabled=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_uuid: str) -> bool:
    user = db.get(ProxyUser, user_uuid)
    if user is None:
        return False

    db.delete(user)
    db.commit()
    return True


def get_user(db: Session, user_uuid: str) -> ProxyUser | None:
    return db.get(ProxyUser, user_uuid)
