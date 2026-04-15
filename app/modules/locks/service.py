import hashlib
import hmac
import secrets

from sqlalchemy.exc import IntegrityError
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
        device_id: str | None = None,
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
        generated_api_key: str | None = None

        device_by_id = (
            self._db.query(LockDeviceModel)
            .filter(LockDeviceModel.id == device_id)
            .one_or_none()
            if device_id
            else None
        )
        device_by_lock_id = (
            self._db.query(LockDeviceModel)
            .filter(LockDeviceModel.lock_id_hash == lock_id_hash)
            .one_or_none()
        )
        device_by_uid = (
            self._db.query(LockDeviceModel)
            .filter(LockDeviceModel.device_uid_hash == uid_hash)
            .one_or_none()
        )
        if device_by_id is not None and device_by_id.owner_email != owner_key:
            raise ValueError("Selected lock belongs to another account.")
        if device_by_lock_id is not None and device_by_lock_id.owner_email != owner_key:
            raise ValueError("Этот замок уже привязан к другому аккаунту.")

        if device_by_uid is not None and device_by_uid.owner_email != owner_key:
            raise ValueError("This board UID is already linked to another account.")
        if device_by_id is not None:
            if device_by_lock_id is not None and device_by_lock_id.id != device_by_id.id:
                raise ValueError("This Lock ID is already used by another saved lock.")
            if device_by_uid is not None and device_by_uid.id != device_by_id.id:
                raise ValueError("This board UID is already used by another saved lock.")
            device = device_by_id
        else:
            if (
                device_by_lock_id is not None
                and device_by_uid is not None
                and device_by_lock_id.id != device_by_uid.id
            ):
                raise ValueError("Lock ID and board UID point to different saved locks.")
            device = device_by_lock_id or device_by_uid

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
            generated_api_key = self._generate_api_key()
            device.api_key_hash = self._hash_uid(generated_api_key)
            device.api_key_encrypted = self._encryption.encrypt(generated_api_key)
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
            if not device.api_key_hash or not device.api_key_encrypted:
                generated_api_key = self._generate_api_key()
                device.api_key_hash = self._hash_uid(generated_api_key)
                device.api_key_encrypted = self._encryption.encrypt(generated_api_key)

        try:
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            raise ValueError("Unable to save lock because Lock ID or board UID is already in use.") from exc
        self._db.refresh(device)
        if generated_api_key is not None:
            setattr(device, "_plain_api_key", generated_api_key)
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

    def delete_device(self, owner_email: str, *, device_id: str) -> None:
        owner_key = owner_email.strip().lower()
        device = (
            self._db.query(LockDeviceModel)
            .filter(LockDeviceModel.id == device_id, LockDeviceModel.owner_email == owner_key)
            .one_or_none()
        )
        if device is None:
            raise ValueError("Saved lock not found.")
        self._db.delete(device)
        self._db.commit()

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
            "door_id": device.door_id or "",
            "lock_id": self._encryption.decrypt(device.lock_id_encrypted),
            "has_api_key": bool(device.api_key_hash),
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

    def export_provisioning_view(self, device: LockDeviceModel, *, api_base_url: str) -> dict[str, str]:
        api_key = getattr(device, "_plain_api_key", None)
        if api_key is None and device.api_key_encrypted:
            api_key = self._encryption.decrypt(device.api_key_encrypted)
        return {
            "lock_id": self._encryption.decrypt(device.lock_id_encrypted),
            "api_key": api_key or "",
            "api_base_url": api_base_url.rstrip("/"),
        }

    def authenticate_device(self, *, lock_id: str, api_key: str) -> LockDeviceModel:
        normalized_lock_id = self._normalize_uid(lock_id)
        device = (
            self._db.query(LockDeviceModel)
            .options(joinedload(LockDeviceModel.door).joinedload(DoorModel.house))
            .filter(LockDeviceModel.lock_id_hash == self._hash_uid(normalized_lock_id))
            .one_or_none()
        )
        if device is None:
            raise ValueError("Замок не найден.")
        if not device.api_key_hash:
            raise ValueError("У замка не настроен API-ключ.")
        if not hmac.compare_digest(device.api_key_hash, self._hash_uid(api_key.strip())):
            raise ValueError("Неверный API-ключ замка.")
        return device

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
    def _generate_api_key() -> str:
        return secrets.token_urlsafe(32)

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
