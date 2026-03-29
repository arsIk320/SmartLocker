from __future__ import annotations

import hashlib
import hmac
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
        period_seconds: int = 30,
        secret_rotation_hours: int = 24,
    ) -> None:
        self._db = db
        self._encryption = encryption
        self._code_length = code_length
        self._period_seconds = period_seconds
        self._secret_rotation_hours = secret_rotation_hours

    def get_current_qr_payload(self, door: DoorModel) -> dict[str, str | int]:
        secret = self._ensure_active_secret(door)
        now = datetime.now(UTC)
        window = int(now.timestamp() // self._period_seconds)
        expires_at = datetime.fromtimestamp((window + 1) * self._period_seconds, tz=UTC)
        code = self._generate_code(secret, door.door_uid, window)
        return {
            "code": code,
            "door_uid": door.door_uid,
            "expires_at": expires_at.isoformat(),
            "ttl_seconds": max(1, int((expires_at - now).total_seconds())),
            "period_seconds": self._period_seconds,
        }

    def rotate_qr_secret(self, door: DoorModel) -> dict[str, str | int]:
        secret = self._issue_new_secret(door)
        self._db.commit()
        self._db.refresh(door)
        payload = self.get_current_qr_payload(door)
        payload["rotated"] = 1
        return payload

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

    def _generate_code(self, secret: str, door_uid: str, window: int) -> str:
        payload = f"{door_uid}:{window}".encode("utf-8")
        digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
        value = int.from_bytes(digest[:8], byteorder="big")
        modulus = 10 ** self._code_length
        return str(value % modulus).zfill(self._code_length)

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
