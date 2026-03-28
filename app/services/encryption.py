import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import Settings


class EncryptionService:
    def __init__(self, settings: Settings) -> None:
        key = settings.data_encryption_key or self._derive_key(settings.jwt_secret_key)
        self._fernet = Fernet(key.encode("utf-8"))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _derive_key(secret: str) -> str:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8")
