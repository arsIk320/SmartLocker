import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import Settings


class EncryptionService:
    def __init__(self, settings: Settings) -> None:
        raw_secret = settings.data_encryption_key or settings.jwt_secret_key
        key = self._normalize_key(raw_secret)
        self._fernet = Fernet(key.encode("utf-8"))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _derive_key(secret: str) -> str:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8")

    @classmethod
    def _normalize_key(cls, secret: str) -> str:
        candidate = secret.strip()
        try:
            Fernet(candidate.encode("utf-8"))
            return candidate
        except Exception:
            return cls._derive_key(candidate)
