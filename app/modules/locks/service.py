import hashlib

from sqlalchemy.orm import Session, joinedload

from app.db.models import DoorModel, LockDeviceModel
from app.services.encryption import EncryptionService


class LockDeviceService:
    def __init__(self, db: Session, encryption: EncryptionService) -> None:
        self._db = db
        self._encryption = encryption

    def save_device(
        self,
        owner_email: str,
        *,
        lock_id: str,
        device_name: str,
        wifi_ssid: str,
        wifi_password: str,
        port_name: str = "",
        door_id: str | None = None,
        esp8266_uid: str = "",
        esp32_uid: str = "",
    ) -> LockDeviceModel:
        owner_key = owner_email.strip().lower()
        normalized_lock_id = self._normalize_uid(lock_id)
        lock_id_hash = self._hash_uid(normalized_lock_id)
        normalized_esp8266_uid = self._normalize_optional_uid(esp8266_uid)
        normalized_esp32_uid = self._normalize_optional_uid(esp32_uid)
        normalized_device_uid = normalized_esp32_uid or normalized_esp8266_uid or normalized_lock_id
        uid_hash = self._hash_uid(normalized_device_uid)

        device = (
            self._db.query(LockDeviceModel)
            .filter(LockDeviceModel.lock_id_hash == lock_id_hash)
            .one_or_none()
        )
        if device is not None and device.owner_email != owner_key:
            raise ValueError("Этот замок уже привязан к другому аккаунту.")

        door = self._get_door(owner_key, door_id) if door_id else None

        if device is None:
            device = LockDeviceModel(
                owner_email=owner_key,
                door_id=door.id if door else None,
                lock_id_hash=lock_id_hash,
                lock_id_encrypted=self._encryption.encrypt(normalized_lock_id),
                device_uid_hash=uid_hash,
                device_uid_encrypted=self._encryption.encrypt(normalized_device_uid),
                esp8266_uid_encrypted=self._encrypt_optional(normalized_esp8266_uid),
                esp32_uid_encrypted=self._encrypt_optional(normalized_esp32_uid),
                device_name_encrypted=self._encryption.encrypt(device_name.strip()),
                wifi_ssid_encrypted=self._encryption.encrypt(wifi_ssid.strip()),
                wifi_password_encrypted=self._encryption.encrypt(wifi_password),
                port_name=port_name.strip() or None,
                status="configured",
            )
            self._db.add(device)
        else:
            device.door_id = door.id if door else None
            device.lock_id_hash = lock_id_hash
            device.lock_id_encrypted = self._encryption.encrypt(normalized_lock_id)
            device.device_uid_hash = uid_hash
            device.device_uid_encrypted = self._encryption.encrypt(normalized_device_uid)
            device.esp8266_uid_encrypted = self._encrypt_optional(normalized_esp8266_uid)
            device.esp32_uid_encrypted = self._encrypt_optional(normalized_esp32_uid)
            device.device_name_encrypted = self._encryption.encrypt(device_name.strip())
            device.wifi_ssid_encrypted = self._encryption.encrypt(wifi_ssid.strip())
            device.wifi_password_encrypted = self._encryption.encrypt(wifi_password)
            device.port_name = port_name.strip() or None
            device.status = "configured"

        self._db.commit()
        self._db.refresh(device)
        return device

    def list_devices(self, owner_email: str) -> list[dict[str, str]]:
        owner_key = owner_email.strip().lower()
        devices = (
            self._db.query(LockDeviceModel)
            .options(joinedload(LockDeviceModel.door).joinedload(DoorModel.house))
            .filter(LockDeviceModel.owner_email == owner_key)
            .order_by(LockDeviceModel.updated_at.desc())
            .all()
        )
        return [self.export_view(device) for device in devices]

    def export_view(self, device: LockDeviceModel) -> dict[str, str]:
        door_name = ""
        door_uid = ""
        house_name = ""
        if device.door is not None:
            door_name = device.door.name
            door_uid = device.door.door_uid
            if device.door.house is not None:
                house_name = device.door.house.name
        return {
            "id": device.id,
            "lock_id": self._encryption.decrypt(device.lock_id_encrypted),
            "device_uid": self._encryption.decrypt(device.device_uid_encrypted),
            "esp8266_uid": self._decrypt_optional(device.esp8266_uid_encrypted),
            "esp32_uid": self._decrypt_optional(device.esp32_uid_encrypted),
            "device_name": self._encryption.decrypt(device.device_name_encrypted),
            "wifi_ssid": self._encryption.decrypt(device.wifi_ssid_encrypted),
            "wifi_password_mask": "*" * 8,
            "port_name": device.port_name or "Не указан",
            "status": device.status,
            "door_name": door_name,
            "door_uid": door_uid,
            "house_name": house_name,
            "updated_at": device.updated_at.isoformat(timespec="seconds"),
        }

    def _get_door(self, owner_email: str, door_id: str) -> DoorModel:
        door = (
            self._db.query(DoorModel)
            .options(joinedload(DoorModel.house))
            .filter(DoorModel.owner_email == owner_email, DoorModel.id == door_id)
            .one_or_none()
        )
        if door is None:
            raise ValueError("Дверь для привязки замка не найдена.")
        return door

    @staticmethod
    def _normalize_uid(device_uid: str) -> str:
        normalized = "".join(ch for ch in device_uid.strip().upper() if ch.isalnum() or ch in {"-", "_"})
        if not normalized:
            raise ValueError("UID замка не может быть пустым.")
        return normalized

    @staticmethod
    def _hash_uid(device_uid: str) -> str:
        return hashlib.sha256(device_uid.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_optional_uid(device_uid: str) -> str | None:
        value = device_uid.strip()
        if not value:
            return None
        normalized = "".join(ch for ch in value.upper() if ch.isalnum() or ch in {"-", "_"})
        return normalized or None

    def _encrypt_optional(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self._encryption.encrypt(value)

    def _decrypt_optional(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self._encryption.decrypt(value)
