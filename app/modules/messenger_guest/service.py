from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.db.models import AccessGrantModel, DoorModel, FacePhotoSubmissionModel
from app.modules.biometrics.face_map import FaceMapError, build_face_maps_from_bytes
from app.modules.locks.qr_service import QrAccessService
from app.services.encryption import EncryptionService


@dataclass
class GuestAccessLookup:
    reservation_external_id: str
    guest_name: str
    door_name: str
    door_uid: str
    house_name: str
    method: str
    valid_from: datetime
    valid_to: datetime
    qr_payload: dict[str, str | int]
    face_profile_status: str
    face_profile_quality_score: float | None
    face_profile_error: str | None
    face_profile_faces_count: int


class MessengerGuestService:
    binding_model: type[Any]
    binding_user_field: str
    face_user_field: str
    channel_label: str

    def __init__(
        self,
        *,
        db: Session,
        encryption: EncryptionService,
        qr_service: QrAccessService,
    ) -> None:
        self._db = db
        self._encryption = encryption
        self._qr_service = qr_service

        missing = [
            name
            for name in ("binding_model", "binding_user_field", "face_user_field", "channel_label")
            if not getattr(self, name, None)
        ]
        if missing:
            raise NotImplementedError(
                f"{self.__class__.__name__} must define messenger metadata: {', '.join(missing)}."
            )

    def search_guest_accesses(
        self,
        *,
        guest_query: str,
    ) -> list[GuestAccessLookup]:
        normalized_query = self._normalize_query(guest_query)
        if not normalized_query:
            raise ValueError("Нужно указать ФИО гостя.")

        query_tokens = self._tokenize(normalized_query)
        grants = self._get_active_grants()

        results: list[GuestAccessLookup] = []
        for grant in grants:
            guest_name = self._encryption.decrypt(grant.guest_name_encrypted)
            if not self._matches_guest(guest_name=guest_name, query=normalized_query, query_tokens=query_tokens):
                continue
            results.append(self._build_lookup(grant=grant, guest_name=guest_name))

        if not results:
            raise ValueError("По указанному ФИО активные брони не найдены.")
        return results

    def _get_bound_guest_accesses(
        self,
        *,
        channel_user_id: str,
    ) -> list[GuestAccessLookup]:
        binding_field = getattr(self.binding_model, self.binding_user_field)
        bindings = (
            self._db.query(self.binding_model)
            .filter(binding_field == channel_user_id)
            .order_by(self.binding_model.created_at.desc())
            .all()
        )
        if not bindings:
            return []

        reservation_ids = [binding.reservation_external_id for binding in bindings]
        grants = (
            self._db.query(AccessGrantModel)
            .options(joinedload(AccessGrantModel.door).joinedload(DoorModel.house))
            .filter(
                AccessGrantModel.reservation_external_id.in_(reservation_ids),
                AccessGrantModel.status == "active",
            )
            .order_by(AccessGrantModel.valid_from.asc())
            .all()
        )
        return [
            self._build_lookup(
                grant=grant,
                guest_name=self._encryption.decrypt(grant.guest_name_encrypted),
            )
            for grant in grants
        ]

    def _bind_guest_booking(
        self,
        *,
        reservation_code: str,
        channel_user_id: str,
    ) -> dict[str, str]:
        access = self.lookup_guest_access_by_reservation(reservation_code=reservation_code)
        binding_field = getattr(self.binding_model, self.binding_user_field)
        binding = (
            self._db.query(self.binding_model)
            .filter(
                binding_field == channel_user_id,
                self.binding_model.reservation_external_id == access.reservation_external_id,
            )
            .one_or_none()
        )
        if binding is None:
            binding = self.binding_model(
                reservation_external_id=access.reservation_external_id,
                guest_name_encrypted=self._encryption.encrypt(access.guest_name),
                **{self.binding_user_field: channel_user_id},
            )
            self._db.add(binding)
        else:
            binding.guest_name_encrypted = self._encryption.encrypt(access.guest_name)

        self._db.commit()
        return {
            "reservation_external_id": access.reservation_external_id,
            "guest_name": access.guest_name,
        }

    def _unbind_guest_booking(
        self,
        *,
        reservation_code: str,
        channel_user_id: str,
    ) -> dict[str, str]:
        normalized_code = reservation_code.strip()
        binding_field = getattr(self.binding_model, self.binding_user_field)
        binding = (
            self._db.query(self.binding_model)
            .filter(
                binding_field == channel_user_id,
                self.binding_model.reservation_external_id == normalized_code,
            )
            .one_or_none()
        )
        if binding is None:
            raise ValueError(f"Бронь не привязана к этому {self.channel_label}.")

        self._db.delete(binding)
        self._db.commit()
        return {
            "reservation_external_id": normalized_code,
            "status": "unbound",
        }

    def lookup_guest_access_by_reservation(
        self,
        *,
        reservation_code: str,
    ) -> GuestAccessLookup:
        normalized_code = reservation_code.strip()
        if not normalized_code:
            raise ValueError("Нужно указать код брони.")

        grant = (
            self._db.query(AccessGrantModel)
            .options(joinedload(AccessGrantModel.door).joinedload(DoorModel.house))
            .filter(
                AccessGrantModel.reservation_external_id == normalized_code,
                AccessGrantModel.status == "active",
            )
            .one_or_none()
        )
        if grant is None:
            raise ValueError("Бронь не найдена.")

        guest_name = self._encryption.decrypt(grant.guest_name_encrypted)
        return self._build_lookup(grant=grant, guest_name=guest_name)

    def _save_face_photo(
        self,
        *,
        reservation_code: str,
        guest_query: str,
        channel_user_id: str,
        photo_bytes: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        access = self.lookup_guest_access_by_reservation(
            reservation_code=reservation_code,
        )
        encoded = base64.b64encode(photo_bytes).decode("ascii")
        submission = FacePhotoSubmissionModel(
            reservation_external_id=access.reservation_external_id,
            guest_name_encrypted=self._encryption.encrypt(access.guest_name),
            guest_contact_encrypted=self._encryption.encrypt(guest_query.strip()),
            content_type=content_type,
            photo_encrypted=self._encryption.encrypt(encoded),
            status="received",
            **{self.face_user_field: channel_user_id},
        )

        try:
            face_maps = build_face_maps_from_bytes(photo_bytes)
            submission.face_map_encrypted = self._encryption.encrypt(
                json.dumps(face_maps, ensure_ascii=False)
            )
            quality_values = [
                float(face_map["quality_score"])
                for face_map in face_maps
                if face_map.get("quality_score") is not None
            ]
            submission.face_quality_score = max(quality_values) if quality_values else None
            submission.face_model_version = str(face_maps[0]["model_version"]) if face_maps else None
            submission.processing_error = None
            submission.processed_at = datetime.now(UTC)
            submission.status = "processed"
        except FaceMapError as exc:
            submission.face_map_encrypted = None
            submission.face_quality_score = None
            submission.face_model_version = None
            submission.processing_error = str(exc)
            submission.processed_at = datetime.now(UTC)
            submission.status = "processing_failed"

        self._db.add(submission)
        self._db.commit()
        self._db.refresh(submission)
        return {
            "submission_id": submission.id,
            "status": submission.status,
            "face_profile_status": self._normalize_face_profile_status(submission.status),
            "quality_score": submission.face_quality_score,
            "processing_error": submission.processing_error or "",
            "faces_count": len(self._decode_face_maps(submission)),
        }

    def serialize_lookup(self, item: GuestAccessLookup) -> dict[str, object]:
        payload = asdict(item)
        payload["valid_from"] = item.valid_from.isoformat()
        payload["valid_to"] = item.valid_to.isoformat()
        return payload

    def _get_active_grants(self) -> list[AccessGrantModel]:
        return (
            self._db.query(AccessGrantModel)
            .options(joinedload(AccessGrantModel.door).joinedload(DoorModel.house))
            .filter(AccessGrantModel.status == "active")
            .order_by(AccessGrantModel.valid_from.asc())
            .all()
        )

    def _build_lookup(
        self,
        *,
        grant: AccessGrantModel,
        guest_name: str,
    ) -> GuestAccessLookup:
        qr_payload = self._qr_service.get_current_qr_payload(grant.door)
        profile = self._face_profile_snapshot(reservation_id=grant.reservation_external_id)
        return GuestAccessLookup(
            reservation_external_id=grant.reservation_external_id,
            guest_name=guest_name,
            door_name=grant.door.name,
            door_uid=grant.door.door_uid,
            house_name=grant.door.house.name,
            method=grant.method,
            valid_from=self._normalize_datetime(grant.valid_from),
            valid_to=self._normalize_datetime(grant.valid_to),
            qr_payload=qr_payload,
            face_profile_status=profile["status"],
            face_profile_quality_score=profile["quality_score"],
            face_profile_error=profile["error"],
            face_profile_faces_count=profile["faces_count"],
        )

    def _latest_face_submission(self, *, reservation_id: str) -> FacePhotoSubmissionModel | None:
        return (
            self._db.query(FacePhotoSubmissionModel)
            .filter(FacePhotoSubmissionModel.reservation_external_id == reservation_id)
            .order_by(FacePhotoSubmissionModel.created_at.desc())
            .first()
        )

    def _face_profile_snapshot(self, *, reservation_id: str) -> dict[str, Any]:
        submissions = (
            self._db.query(FacePhotoSubmissionModel)
            .filter(FacePhotoSubmissionModel.reservation_external_id == reservation_id)
            .order_by(FacePhotoSubmissionModel.created_at.desc())
            .all()
        )
        if not submissions:
            return {
                "status": "missing",
                "quality_score": None,
                "error": None,
                "faces_count": 0,
            }

        latest_submission = submissions[0]
        processed_face_maps: list[dict[str, Any]] = []
        for submission in submissions:
            if submission.status != "processed":
                continue
            processed_face_maps.extend(self._decode_face_maps(submission))

        if processed_face_maps:
            quality_values = [
                self._safe_float(face_map.get("quality_score"))
                for face_map in processed_face_maps
                if self._safe_float(face_map.get("quality_score")) is not None
            ]
            return {
                "status": "processed",
                "quality_score": max(quality_values) if quality_values else latest_submission.face_quality_score,
                "error": None,
                "faces_count": len(processed_face_maps),
            }

        return {
            "status": self._normalize_face_profile_status(latest_submission.status),
            "quality_score": latest_submission.face_quality_score,
            "error": latest_submission.processing_error,
            "faces_count": 0,
        }

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
    def _normalize_face_profile_status(status: str | None) -> str:
        if status == "processed":
            return "processed"
        if status in {"received", "processing"}:
            return "processing"
        if status == "processing_failed":
            return "failed"
        return "missing"

    @staticmethod
    def _normalize_query(value: str) -> str:
        return " ".join(value.strip().lower().split())

    @staticmethod
    def _tokenize(value: str) -> set[str]:
        return {token.strip("., ").lower() for token in value.split() if token.strip()}

    def _matches_guest(
        self,
        *,
        guest_name: str,
        query: str,
        query_tokens: set[str],
    ) -> bool:
        guest_normalized = self._normalize_query(guest_name)
        guest_tokens = self._tokenize(guest_normalized)

        if query == guest_normalized:
            return True
        if query in guest_normalized:
            return True
        if len(query_tokens) >= 2 and query_tokens.issubset(guest_tokens):
            return True
        if len(query_tokens) == 1 and any(token.startswith(next(iter(query_tokens))) for token in guest_tokens):
            return True

        overlap = query_tokens.intersection(guest_tokens)
        return len(overlap) >= min(2, len(query_tokens))

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _safe_float(value: object) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None
