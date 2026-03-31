import hashlib
from secrets import token_hex

from sqlalchemy.orm import Session, joinedload

from app.db.models import AccessGrantModel, DoorModel, HouseModel
from app.models.domain import Reservation, ReservationStatus
from app.services.encryption import EncryptionService


class PropertyService:
    def __init__(self, db: Session, encryption: EncryptionService) -> None:
        self._db = db
        self._encryption = encryption

    def list_houses(self, owner_email: str) -> list[HouseModel]:
        return (
            self._db.query(HouseModel)
            .options(joinedload(HouseModel.doors))
            .filter(HouseModel.owner_email == owner_email.strip().lower())
            .order_by(HouseModel.created_at.asc())
            .all()
        )

    def add_house(self, owner_email: str, *, name: str, address: str) -> HouseModel:
        house = HouseModel(
            owner_email=owner_email.strip().lower(),
            name=name.strip(),
            address_encrypted=self._encryption.encrypt(address.strip()),
        )
        self._db.add(house)
        self._db.commit()
        self._db.refresh(house)
        return house

    def add_door(
        self,
        owner_email: str,
        *,
        house_id: str,
        name: str,
        lock_label: str,
        travelline_unit_id: str | None = None,
    ) -> DoorModel:
        house = self._get_house(owner_email=owner_email, house_id=house_id)
        door = DoorModel(
            door_uid=self._generate_door_uid(),
            owner_email=house.owner_email,
            house_id=house.id,
            name=name.strip(),
            lock_label_encrypted=self._encryption.encrypt(lock_label.strip()),
            travelline_unit_id=travelline_unit_id.strip() if travelline_unit_id else None,
        )
        self._db.add(door)
        self._db.commit()
        self._db.refresh(door)
        return door

    def bind_lock_uid(
        self,
        owner_email: str,
        *,
        door_id: str,
        lock_uid: str,
    ) -> DoorModel:
        door = self._get_door(owner_email=owner_email, door_id=door_id)
        normalized_uid = self._normalize_lock_uid(lock_uid)
        uid_hash = self._hash_lock_uid(normalized_uid)

        existing = (
            self._db.query(DoorModel)
            .filter(DoorModel.lock_uid_hash == uid_hash, DoorModel.id != door.id)
            .one_or_none()
        )
        if existing is not None:
            raise ValueError("Этот UID замка уже привязан к другой двери.")

        door.lock_uid_hash = uid_hash
        door.lock_uid_encrypted = self._encryption.encrypt(normalized_uid)
        self._db.commit()
        self._db.refresh(door)
        return door

    def find_door_by_lock_uid(self, lock_uid: str) -> DoorModel | None:
        normalized_uid = self._normalize_lock_uid(lock_uid)
        uid_hash = self._hash_lock_uid(normalized_uid)
        return (
            self._db.query(DoorModel)
            .options(joinedload(DoorModel.house))
            .filter(DoorModel.lock_uid_hash == uid_hash)
            .one_or_none()
        )

    def sync_houses_from_travelline(
        self,
        *,
        owner_email: str,
        properties: list[dict[str, object]],
    ) -> list[HouseModel]:
        owner_key = owner_email.strip().lower()
        existing_houses = self.list_houses(owner_key)
        house_by_name = {house.name: house for house in existing_houses}
        door_by_unit = {
            door.travelline_unit_id: door
            for house in existing_houses
            for door in house.doors
            if door.travelline_unit_id
        }

        touched_houses: list[HouseModel] = []
        for property_item in properties:
            property_name = str(property_item.get("name", "")).strip() or "Объект TravelLine"
            property_address = str(property_item.get("address", "")).strip() or "Адрес не указан"
            room_types = property_item.get("room_types", [])

            house = house_by_name.get(property_name)
            if house is None:
                house = HouseModel(
                    owner_email=owner_key,
                    name=property_name,
                    address_encrypted=self._encryption.encrypt(property_address),
                )
                self._db.add(house)
                self._db.flush()
                house_by_name[property_name] = house
            else:
                house.address_encrypted = self._encryption.encrypt(property_address)

            if isinstance(room_types, list):
                for room_type in room_types:
                    if not isinstance(room_type, dict):
                        continue
                    unit_id = str(room_type.get("id", "")).strip()
                    if not unit_id:
                        continue

                    door = door_by_unit.get(unit_id)
                    room_name = str(room_type.get("name", f"Door {unit_id}")).strip()
                    if door is None:
                        door = DoorModel(
                            door_uid=self._generate_door_uid(),
                            owner_email=owner_key,
                            house_id=house.id,
                            name=room_name,
                            lock_label_encrypted=self._encryption.encrypt("Замок не назначен"),
                            travelline_unit_id=unit_id,
                        )
                        self._db.add(door)
                        door_by_unit[unit_id] = door
                    else:
                        door.name = room_name
            touched_houses.append(house)

        self._db.commit()
        return touched_houses

    def sync_access_grants(
        self,
        *,
        owner_email: str,
        reservations: list[Reservation],
    ) -> list[AccessGrantModel]:
        owner_key = owner_email.strip().lower()
        doors = (
            self._db.query(DoorModel)
            .filter(DoorModel.owner_email == owner_key, DoorModel.travelline_unit_id.is_not(None))
            .all()
        )
        door_by_unit = {door.travelline_unit_id: door for door in doors if door.travelline_unit_id}
        managed_door_ids = {door.id for door in doors}
        if not managed_door_ids:
            return []

        existing_grants = (
            self._db.query(AccessGrantModel)
            .filter(
                AccessGrantModel.owner_email == owner_key,
                AccessGrantModel.door_id.in_(managed_door_ids),
            )
            .all()
        )
        existing_by_key = {
            (grant.reservation_external_id, grant.door_id): grant
            for grant in existing_grants
        }

        grants: list[AccessGrantModel] = []
        seen_keys: set[tuple[str, str]] = set()
        for reservation in reservations:
            unit_id = reservation.unit_external_id or ""
            door = door_by_unit.get(unit_id)
            if door is None:
                continue

            seen_key = (reservation.external_id, door.id)
            is_active_reservation = self._is_reservation_access_active(reservation)
            if is_active_reservation:
                seen_keys.add(seen_key)

            grant = existing_by_key.get(seen_key)
            if grant is None and is_active_reservation:
                grant = AccessGrantModel(
                    owner_email=owner_key,
                    reservation_external_id=reservation.external_id,
                    door_id=door.id,
                    guest_name_encrypted=self._encryption.encrypt(reservation.guest_name),
                    method="pin",
                    status="active",
                    valid_from=reservation.check_in,
                    valid_to=reservation.check_out,
                )
                self._db.add(grant)
            elif grant is not None:
                grant.guest_name_encrypted = self._encryption.encrypt(reservation.guest_name)
                grant.valid_from = reservation.check_in
                grant.valid_to = reservation.check_out
                grant.status = "active" if is_active_reservation else "inactive"

            if grant is not None:
                grants.append(grant)

        for key, grant in existing_by_key.items():
            if key not in seen_keys and grant.status == "active":
                grant.status = "inactive"

        self._db.commit()
        return grants

    def list_access_grants(self, owner_email: str) -> list[dict[str, str]]:
        owner_key = owner_email.strip().lower()
        grants = (
            self._db.query(AccessGrantModel)
            .options(joinedload(AccessGrantModel.door).joinedload(DoorModel.house))
            .filter(
                AccessGrantModel.owner_email == owner_key,
                AccessGrantModel.status == "active",
            )
            .order_by(AccessGrantModel.valid_from.desc())
            .all()
        )

        return [
            {
                "id": grant.id,
                "reservation_external_id": grant.reservation_external_id,
                "guest_name": self._encryption.decrypt(grant.guest_name_encrypted),
                "method": grant.method,
                "status": grant.status,
                "valid_from": grant.valid_from.isoformat(),
                "valid_to": grant.valid_to.isoformat(),
                "door_name": grant.door.name,
                "door_uid": grant.door.door_uid,
                "lock_uid": self._decrypt_lock_uid(grant.door),
                "house_name": grant.door.house.name,
            }
            for grant in grants
        ]

    def export_house_view(self, house: HouseModel) -> dict[str, object]:
        return {
            "id": house.id,
            "name": house.name,
            "address": self._encryption.decrypt(house.address_encrypted),
            "doors": [
                {
                    "id": door.id,
                    "door_uid": door.door_uid,
                    "name": door.name,
                    "lock_label": self._encryption.decrypt(door.lock_label_encrypted),
                    "lock_uid": self._decrypt_lock_uid(door),
                    "travelline_unit_id": door.travelline_unit_id,
                }
                for door in sorted(house.doors, key=lambda item: item.created_at)
            ],
        }

    def _get_house(self, *, owner_email: str, house_id: str) -> HouseModel:
        house = (
            self._db.query(HouseModel)
            .filter(
                HouseModel.owner_email == owner_email.strip().lower(),
                HouseModel.id == house_id,
            )
            .one_or_none()
        )
        if house is None:
            raise ValueError("Дом не найден.")
        return house

    def _get_door(self, *, owner_email: str, door_id: str) -> DoorModel:
        door = (
            self._db.query(DoorModel)
            .filter(
                DoorModel.owner_email == owner_email.strip().lower(),
                DoorModel.id == door_id,
            )
            .one_or_none()
        )
        if door is None:
            raise ValueError("Дверь не найдена.")
        return door

    def _generate_door_uid(self) -> str:
        while True:
            candidate = token_hex(5).upper()
            exists = self._db.query(DoorModel).filter(DoorModel.door_uid == candidate).one_or_none()
            if exists is None:
                return candidate

    @staticmethod
    def _normalize_lock_uid(lock_uid: str) -> str:
        normalized = "".join(ch for ch in lock_uid.strip().upper() if ch.isalnum() or ch in {"-", "_"})
        if not normalized:
            raise ValueError("UID замка не может быть пустым.")
        return normalized

    @staticmethod
    def _hash_lock_uid(lock_uid: str) -> str:
        return hashlib.sha256(lock_uid.encode("utf-8")).hexdigest()

    def _decrypt_lock_uid(self, door: DoorModel) -> str | None:
        if not door.lock_uid_encrypted:
            return None
        return self._encryption.decrypt(door.lock_uid_encrypted)

    @staticmethod
    def _is_reservation_access_active(reservation: Reservation) -> bool:
        return reservation.status in {
            ReservationStatus.pending,
            ReservationStatus.confirmed,
            ReservationStatus.checked_in,
        }
