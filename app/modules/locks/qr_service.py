from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import DoorModel
from app.services.encryption import EncryptionService


class QrAccessService:
    def __init__(
        self,
        db: Session,
        encryption: EncryptionService,
        *,
        code_length: int = 11,
        lifetime_seconds: int = 3600,
        secret_rotation_hours: int = 24,
    ) -> None:
        self._db = db
        self._encryption = encryption
        self._code_length = code_length
        self._lifetime_seconds = lifetime_seconds
        self._secret_rotation_hours = secret_rotation_hours

    def get_current_qr_payload(self, door: DoorModel) -> dict[str, str | int]:
        self._ensure_active_secret(door)
        now = datetime.now(UTC)
        issued_at = self._normalize_datetime(door.current_qr_issued_at)
        expires_at = self._normalize_datetime(door.current_qr_expires_at)

        if (
            not door.current_qr_code_encrypted
            or issued_at is None
            or expires_at is None
            or expires_at <= now
        ):
            return self._issue_new_qr(door)

        code = self._encryption.decrypt(door.current_qr_code_encrypted)
        return self._build_payload(
            door=door,
            code=code,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def rotate_qr_secret(self, door: DoorModel) -> dict[str, str | int]:
        self._issue_new_secret(door)
        return self._issue_new_qr(door, rotated=1)

    def _issue_new_qr(self, door: DoorModel, *, rotated: int | None = None) -> dict[str, str | int]:
        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(seconds=self._lifetime_seconds)
        code = "".join(secrets.choice("0123456789") for _ in range(self._code_length))
        door.current_qr_code_encrypted = self._encryption.encrypt(code)
        door.current_qr_issued_at = issued_at
        door.current_qr_expires_at = expires_at
        self._db.commit()
        self._db.refresh(door)
        payload = self._build_payload(
            door=door,
            code=code,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        if rotated is not None:
            payload["rotated"] = rotated
        return payload

    def _build_payload(
        self,
        *,
        door: DoorModel,
        code: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> dict[str, str | int]:
        now = datetime.now(UTC)
        return {
            "code": code,
            "door_uid": door.door_uid,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "ttl_seconds": max(1, int((expires_at - now).total_seconds())),
            "valid_for_seconds": self._lifetime_seconds,
        }

    def _ensure_active_secret(self, door: DoorModel) -> str:
        rotated_at = self._normalize_datetime(door.qr_secret_rotated_at)
        if not door.qr_secret_encrypted or rotated_at is None:
            secret = self._issue_new_secret(door)
            self._db.commit()
            self._db.refresh(door)
            return secret

        if datetime.now(UTC) - rotated_at >= timedelta(hours=self._secret_rotation_hours):
            secret = self._issue_new_secret(door)
            self._db.commit()
            self._db.refresh(door)
            return secret

        return self._encryption.decrypt(door.qr_secret_encrypted)

    def _issue_new_secret(self, door: DoorModel) -> str:
        secret = secrets.token_urlsafe(32)
        door.qr_secret_encrypted = self._encryption.encrypt(secret)
        door.qr_secret_rotated_at = datetime.now(UTC)
        return secret

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
