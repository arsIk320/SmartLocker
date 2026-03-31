from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import AccessAttemptLogModel
from app.services.encryption import EncryptionService


@dataclass
class AccessAttemptLogView:
    created_at: str
    method: str
    source: str
    result: str
    reason: str
    reservation_external_id: str | None
    door_uid: str | None
    guest_name: str | None
    distance: float | None
    confidence: float | None
    threshold: float | None
    probe_quality_score: float | None


class AccessAttemptLogService:
    def __init__(self, *, db: Session, encryption: EncryptionService) -> None:
        self._db = db
        self._encryption = encryption

    def record_attempt(
        self,
        *,
        owner_email: str,
        method: str,
        source: str,
        result: str,
        reason: str,
        reservation_external_id: str | None = None,
        door_uid: str | None = None,
        guest_name: str | None = None,
        distance: float | None = None,
        confidence: float | None = None,
        threshold: float | None = None,
        probe_quality_score: float | None = None,
    ) -> None:
        entry = AccessAttemptLogModel(
            owner_email=owner_email,
            reservation_external_id=reservation_external_id,
            door_uid=door_uid,
            method=method,
            source=source,
            result=result,
            reason=reason,
            guest_name_encrypted=self._encryption.encrypt(guest_name) if guest_name else None,
            distance=distance,
            confidence=confidence,
            threshold=threshold,
            probe_quality_score=probe_quality_score,
        )
        self._db.add(entry)
        self._db.commit()

    def list_recent(self, *, owner_email: str, limit: int = 100) -> list[AccessAttemptLogView]:
        rows = (
            self._db.query(AccessAttemptLogModel)
            .filter(AccessAttemptLogModel.owner_email == owner_email)
            .order_by(AccessAttemptLogModel.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            AccessAttemptLogView(
                created_at=row.created_at.isoformat() if row.created_at else "",
                method=row.method,
                source=row.source,
                result=row.result,
                reason=row.reason,
                reservation_external_id=row.reservation_external_id,
                door_uid=row.door_uid,
                guest_name=self._encryption.decrypt(row.guest_name_encrypted) if row.guest_name_encrypted else None,
                distance=row.distance,
                confidence=row.confidence,
                threshold=row.threshold,
                probe_quality_score=row.probe_quality_score,
            )
            for row in rows
        ]
