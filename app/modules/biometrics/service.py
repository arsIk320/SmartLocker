from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from app.db.models import AccessGrantModel, FacePhotoSubmissionModel
from app.core.config import get_settings
from app.modules.biometrics.face_map import FaceMapError, build_face_map_from_bytes
from app.services.encryption import EncryptionService


@dataclass
class FaceProfileView:
    reservation_external_id: str
    guest_name: str
    quality_score: float | None
    processed_at: str | None
    status: str


@dataclass
class FaceCompareResult:
    reservation_external_id: str
    guest_name: str
    match: bool
    distance: float
    confidence: float
    threshold: float
    stored_quality_score: float | None
    probe_quality_score: float | None


class FaceVerificationService:
    def __init__(self, *, db: Session, encryption: EncryptionService) -> None:
        self._db = db
        self._encryption = encryption
        self._threshold = get_settings().face_match_distance_threshold

    def list_profiles(self, *, owner_email: str) -> list[FaceProfileView]:
        grants = (
            self._db.query(AccessGrantModel)
            .filter(AccessGrantModel.owner_email == owner_email)
            .order_by(AccessGrantModel.valid_from.desc())
            .all()
        )

        seen: set[str] = set()
        profiles: list[FaceProfileView] = []
        for grant in grants:
            reservation_id = grant.reservation_external_id
            if reservation_id in seen:
                continue
            seen.add(reservation_id)
            submission = self._latest_submission(reservation_id=reservation_id)
            if submission is None:
                continue
            profiles.append(
                FaceProfileView(
                    reservation_external_id=reservation_id,
                    guest_name=self._encryption.decrypt(grant.guest_name_encrypted),
                    quality_score=submission.face_quality_score,
                    processed_at=submission.processed_at.isoformat() if submission.processed_at else None,
                    status=submission.status,
                )
            )
        return profiles

    def compare_probe(
        self,
        *,
        owner_email: str,
        reservation_external_id: str,
        image_bytes: bytes,
        threshold_override: float | None = None,
        min_probe_quality_score: float | None = None,
    ) -> FaceCompareResult:
        grant = (
            self._db.query(AccessGrantModel)
            .filter(
                AccessGrantModel.owner_email == owner_email,
                AccessGrantModel.reservation_external_id == reservation_external_id,
            )
            .one_or_none()
        )
        if grant is None:
            raise ValueError("Бронь для проверки не найдена.")

        submission = self._latest_submission(reservation_id=reservation_external_id)
        if submission is None or not submission.face_map_encrypted:
            raise ValueError("Для этой брони ещё нет построенной карты лица.")
        if submission.status != "processed":
            raise ValueError("Карта лица для этой брони ещё не готова.")

        stored_map = json.loads(self._encryption.decrypt(submission.face_map_encrypted))
        probe_map = build_face_map_from_bytes(image_bytes)
        probe_quality_score = float(probe_map["quality_score"])
        if min_probe_quality_score is not None and probe_quality_score < min_probe_quality_score:
            raise ValueError(
                f"Live probe quality is too low. quality_score={probe_quality_score:.4f}, "
                f"required>={min_probe_quality_score:.4f}"
            )

        stored_embedding = np.array(stored_map["embedding"], dtype=np.float32)
        probe_embedding = np.array(probe_map["embedding"], dtype=np.float32)
        distance = float(np.linalg.norm(stored_embedding - probe_embedding))
        confidence = max(0.0, min(1.0, 1.0 - distance / 1.5))
        threshold = threshold_override if threshold_override is not None else self._threshold

        return FaceCompareResult(
            reservation_external_id=reservation_external_id,
            guest_name=self._encryption.decrypt(grant.guest_name_encrypted),
            match=distance <= threshold,
            distance=round(distance, 4),
            confidence=round(confidence, 4),
            threshold=round(float(threshold), 4),
            stored_quality_score=submission.face_quality_score,
            probe_quality_score=probe_quality_score,
        )

    def _latest_submission(self, *, reservation_id: str) -> FacePhotoSubmissionModel | None:
        return (
            self._db.query(FacePhotoSubmissionModel)
            .filter(FacePhotoSubmissionModel.reservation_external_id == reservation_id)
            .order_by(FacePhotoSubmissionModel.created_at.desc())
            .first()
        )


def decode_data_url_image(image_data: str) -> bytes:
    if "," not in image_data:
        raise ValueError("Некорректный формат снимка.")
    _, encoded = image_data.split(",", 1)
    try:
        return base64.b64decode(encoded)
    except Exception as exc:
        raise ValueError("Не удалось декодировать снимок с камеры.") from exc
