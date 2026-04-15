from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AccessGrantModel, FacePhotoSubmissionModel
from app.modules.biometrics.face_map import build_face_map_from_bytes
from app.services.encryption import EncryptionService


@dataclass
class FaceProfileView:
    reservation_external_id: str
    guest_name: str
    quality_score: float | None
    processed_at: str | None
    status: str
    faces_count: int


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
    stored_faces_count: int


class FaceVerificationUnavailableError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
            profile = self._build_face_profile(reservation_id=reservation_id)
            if profile is None:
                continue
            profiles.append(
                FaceProfileView(
                    reservation_external_id=reservation_id,
                    guest_name=self._encryption.decrypt(grant.guest_name_encrypted),
                    quality_score=profile["quality_score"],
                    processed_at=(
                        profile["processed_at"].isoformat() if profile["processed_at"] is not None else None
                    ),
                    status=profile["status"],
                    faces_count=profile["faces_count"],
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
            raise FaceVerificationUnavailableError(
                "reservation_not_found",
                "Reservation for face verification was not found.",
            )

        submissions = self._submissions_for_reservation(reservation_id=reservation_external_id)
        if not submissions:
            raise FaceVerificationUnavailableError(
                "stored_face_map_missing",
                "No stored face map is available for this reservation.",
            )
        stored_maps = self._collect_stored_face_maps(submissions)
        if not stored_maps:
            if any(submission.status in {"received", "processing"} for submission in submissions):
                raise FaceVerificationUnavailableError(
                    "stored_face_map_not_ready",
                    "Stored face map for this reservation is not processed yet.",
                )
            raise FaceVerificationUnavailableError(
                "stored_face_map_missing",
                "No stored face map is available for this reservation.",
            )

        probe_map = build_face_map_from_bytes(image_bytes)
        probe_quality_score = float(probe_map["quality_score"])
        if min_probe_quality_score is not None and probe_quality_score < min_probe_quality_score:
            raise FaceVerificationUnavailableError(
                "probe_quality_too_low",
                f"Live probe quality is too low. quality_score={probe_quality_score:.4f}, "
                f"required>={min_probe_quality_score:.4f}",
            )

        probe_embedding = np.array(probe_map["embedding"], dtype=np.float32)
        best_distance: float | None = None
        best_stored_map: dict[str, Any] | None = None
        for stored_map in stored_maps:
            stored_embedding = np.array(stored_map["embedding"], dtype=np.float32)
            distance = float(np.linalg.norm(stored_embedding - probe_embedding))
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_stored_map = stored_map

        if best_distance is None or best_stored_map is None:
            raise FaceVerificationUnavailableError(
                "stored_face_map_missing",
                "No stored face map is available for this reservation.",
            )

        distance = best_distance
        confidence = max(0.0, min(1.0, 1.0 - distance / 1.5))
        threshold = threshold_override if threshold_override is not None else self._threshold

        return FaceCompareResult(
            reservation_external_id=reservation_external_id,
            guest_name=self._encryption.decrypt(grant.guest_name_encrypted),
            match=distance <= threshold,
            distance=round(distance, 4),
            confidence=round(confidence, 4),
            threshold=round(float(threshold), 4),
            stored_quality_score=self._safe_float(best_stored_map.get("quality_score")),
            probe_quality_score=probe_quality_score,
            stored_faces_count=len(stored_maps),
        )

    def _submissions_for_reservation(self, *, reservation_id: str) -> list[FacePhotoSubmissionModel]:
        return (
            self._db.query(FacePhotoSubmissionModel)
            .filter(FacePhotoSubmissionModel.reservation_external_id == reservation_id)
            .order_by(
                FacePhotoSubmissionModel.created_at.desc(),
                FacePhotoSubmissionModel.updated_at.desc(),
            )
            .all()
        )

    def _build_face_profile(self, *, reservation_id: str) -> dict[str, Any] | None:
        submissions = self._submissions_for_reservation(reservation_id=reservation_id)
        if not submissions:
            return None

        latest_submission = submissions[0]
        stored_maps = self._collect_stored_face_maps(submissions)
        faces_count = len(stored_maps)
        processed_at_candidates = [
            submission.processed_at
            for submission in submissions
            if submission.processed_at is not None and submission.status == "processed"
        ]
        latest_processed_at = max(processed_at_candidates) if processed_at_candidates else latest_submission.processed_at

        if faces_count:
            quality_values = [
                self._safe_float(face_map.get("quality_score"))
                for face_map in stored_maps
                if self._safe_float(face_map.get("quality_score")) is not None
            ]
            return {
                "status": "processed",
                "quality_score": max(quality_values) if quality_values else latest_submission.face_quality_score,
                "processed_at": latest_processed_at,
                "faces_count": faces_count,
                "error": None,
            }

        if any(submission.status in {"received", "processing"} for submission in submissions):
            status = "processing"
        elif any(submission.status == "processing_failed" for submission in submissions):
            status = "failed"
        else:
            status = "missing"

        return {
            "status": status,
            "quality_score": latest_submission.face_quality_score,
            "processed_at": latest_submission.processed_at,
            "faces_count": 0,
            "error": latest_submission.processing_error,
        }

    def _collect_stored_face_maps(
        self,
        submissions: list[FacePhotoSubmissionModel],
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for submission in submissions:
            if submission.status != "processed" or not submission.face_map_encrypted:
                continue
            collected.extend(self._decode_face_maps(submission))
        return collected

    def _decode_face_maps(self, submission: FacePhotoSubmissionModel) -> list[dict[str, Any]]:
        if not submission.face_map_encrypted:
            return []
        try:
            payload = json.loads(self._encryption.decrypt(submission.face_map_encrypted))
        except Exception:
            return []

        if isinstance(payload, dict):
            candidates = [payload]
        elif isinstance(payload, list):
            candidates = [item for item in payload if isinstance(item, dict)]
        else:
            candidates = []

        decoded: list[dict[str, Any]] = []
        for candidate in candidates:
            embedding = candidate.get("embedding")
            if isinstance(embedding, list) and embedding:
                decoded.append(candidate)
        return decoded

    @staticmethod
    def _safe_float(value: object) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None


def decode_data_url_image(image_data: str) -> bytes:
    if "," not in image_data:
        raise ValueError("Invalid image payload format.")
    _, encoded = image_data.split(",", 1)
    try:
        return base64.b64decode(encoded)
    except Exception as exc:
        raise ValueError("Unable to decode image from camera.") from exc
