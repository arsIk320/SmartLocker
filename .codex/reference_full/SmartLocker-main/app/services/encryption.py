import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings


class EncryptionService:
    def __init__(self, settings: Settings) -> None:
        raw_secret = settings.data_encryption_key or settings.jwt_secret_key
        self._fernet = self._build_fernet(raw_secret)
        self._legacy_fernets: list[Fernet] = []
        legacy_candidates = []
        if settings.data_encryption_key_legacy:
            legacy_candidates.extend(
                item.strip()
                for item in settings.data_encryption_key_legacy.split(",")
                if item.strip()
            )
        if settings.data_encryption_key and settings.jwt_secret_key != settings.data_encryption_key:
            legacy_candidates.append(settings.jwt_secret_key)
        for candidate in legacy_candidates:
            self._legacy_fernets.append(self._build_fernet(candidate))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        token = value.encode("utf-8")
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken:
            for legacy_fernet in self._legacy_fernets:
                try:
                    return legacy_fernet.decrypt(token).decode("utf-8")
                except InvalidToken:
                    continue
            raise

    @classmethod
    def _build_fernet(cls, secret: str) -> Fernet:
        key = cls._normalize_key(secret)
        return Fernet(key.encode("utf-8"))

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
