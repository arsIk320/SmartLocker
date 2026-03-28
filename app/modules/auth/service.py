import hashlib
import hmac
import secrets
from datetime import UTC, date, datetime, timedelta

from jose import JWTError, jwt
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import AuthUserModel
from app.modules.auth.models import AuthUser
from app.services.email import EmailService
from app.services.encryption import EncryptionService


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        encryption: EncryptionService,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._email_service = EmailService(settings=settings)
        self._encryption = encryption
        self._seed_admin()

    def register_user(
        self,
        *,
        full_name: str,
        phone: str,
        birth_date: date,
        email: str,
        password: str,
    ) -> AuthUser:
        normalized_email = email.strip().lower()
        if self.get_user(normalized_email) is not None:
            raise ValueError("Пользователь с таким email уже существует.")
        if self._calculate_age(birth_date) < 18:
            raise ValueError("Регистрация доступна только пользователям старше 18 лет.")

        verification_code = f"{secrets.randbelow(10**6):06d}"
        now = datetime.now(UTC)

        with self._session_factory() as db:
            model = AuthUserModel(
                email=normalized_email,
                full_name=full_name.strip(),
                phone_encrypted=self._encryption.encrypt(phone.strip()),
                birth_date_encrypted=self._encryption.encrypt(birth_date.isoformat()),
                password_hash=self._hash_password(password),
                role="user",
                is_verified="false",
                verification_code_encrypted=self._encryption.encrypt(verification_code),
                verification_code_expires_at=now + timedelta(minutes=15),
            )
            db.add(model)
            db.commit()
            db.refresh(model)

        user = self._to_auth_user(model)
        self._send_verification_code(user, verification_code)
        return user

    def verify_user(self, *, email: str, code: str) -> AuthUser:
        with self._session_factory() as db:
            model = self._get_user_model(db, email)
            expires_at = self._normalize_datetime(model.verification_code_expires_at)
            if expires_at is None or expires_at < datetime.now(UTC):
                raise ValueError("Срок действия кода подтверждения истёк.")

            stored_code = self._decrypt_optional(model.verification_code_encrypted)
            if stored_code != code.strip():
                raise ValueError("Неверный код подтверждения.")

            model.is_verified = "true"
            model.verification_code_encrypted = None
            model.verification_code_expires_at = None
            db.commit()
            db.refresh(model)
            return self._to_auth_user(model)

    def authenticate(self, *, email: str, password: str) -> AuthUser:
        with self._session_factory() as db:
            model = self._get_user_model(db, email)
            if not self._verify_password(password, model.password_hash):
                raise ValueError("Неверный email или пароль.")
            if model.is_verified != "true":
                raise ValueError("Email не подтверждён. Сначала введите код из письма.")
            return self._to_auth_user(model)

    def request_password_reset(self, *, email: str) -> AuthUser:
        reset_code = f"{secrets.randbelow(10**6):06d}"
        with self._session_factory() as db:
            model = self._get_user_model(db, email)
            model.reset_code_encrypted = self._encryption.encrypt(reset_code)
            model.reset_code_expires_at = datetime.now(UTC) + timedelta(minutes=15)
            db.commit()
            db.refresh(model)
            user = self._to_auth_user(model)

        self._send_reset_code(user, reset_code)
        return user

    def confirm_password_reset(
        self,
        *,
        email: str,
        code: str,
        new_password: str,
    ) -> AuthUser:
        with self._session_factory() as db:
            model = self._get_user_model(db, email)
            stored_code = self._decrypt_optional(model.reset_code_encrypted)
            if stored_code != code.strip():
                raise ValueError("Неверный код сброса пароля.")

            expires_at = self._normalize_datetime(model.reset_code_expires_at)
            if expires_at is None or expires_at < datetime.now(UTC):
                raise ValueError("Срок действия кода сброса истёк.")

            model.password_hash = self._hash_password(new_password)
            model.reset_code_encrypted = None
            model.reset_code_expires_at = None
            db.commit()
            db.refresh(model)
            return self._to_auth_user(model)

    def create_session_token(self, user: AuthUser) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": user.email,
            "role": user.role,
            "name": user.full_name,
            "exp": now + timedelta(days=self._settings.session_persist_days),
            "iat": now,
        }
        return jwt.encode(
            payload,
            self._settings.jwt_secret_key,
            algorithm=self._settings.jwt_algorithm,
        )

    def decode_session_token(self, token: str) -> AuthUser | None:
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret_key,
                algorithms=[self._settings.jwt_algorithm],
            )
        except JWTError:
            return None

        email = str(payload.get("sub", "")).strip().lower()
        if not email:
            return None
        return self.get_user(email)

    def get_user(self, email: str) -> AuthUser | None:
        with self._session_factory() as db:
            model = (
                db.query(AuthUserModel)
                .filter(AuthUserModel.email == email.strip().lower())
                .one_or_none()
            )
            return self._to_auth_user(model) if model is not None else None

    def list_users(self) -> list[AuthUser]:
        with self._session_factory() as db:
            models = db.query(AuthUserModel).order_by(AuthUserModel.created_at.asc()).all()
            return [self._to_auth_user(model) for model in models]

    def export_user_view(self, user: AuthUser) -> dict[str, str]:
        birth_date = self._decrypt_birth_date(user)
        return {
            "full_name": user.full_name,
            "email": user.email,
            "phone": self._decrypt_phone(user),
            "birth_date": birth_date.isoformat(),
            "role": user.role,
            "is_verified": "Да" if user.is_verified else "Нет",
            "created_at": str(user.created_at),
        }

    def _get_user_model(self, db: Session, email: str) -> AuthUserModel:
        model = (
            db.query(AuthUserModel)
            .filter(AuthUserModel.email == email.strip().lower())
            .one_or_none()
        )
        if model is None:
            raise ValueError("Пользователь не найден.")
        return model

    def _seed_admin(self) -> None:
        email = self._settings.admin_email.strip().lower()
        with self._session_factory() as db:
            exists = (
                db.query(AuthUserModel)
                .filter(AuthUserModel.email == email)
                .one_or_none()
            )
            if exists is not None:
                return
            db.add(
                AuthUserModel(
                    email=email,
                    full_name="Администратор проекта",
                    phone_encrypted=self._encryption.encrypt("+70000000000"),
                    birth_date_encrypted=self._encryption.encrypt(date(1995, 1, 1).isoformat()),
                    password_hash=self._hash_password(self._settings.admin_password),
                    role="admin",
                    is_verified="true",
                )
            )
            db.commit()

    def _to_auth_user(self, model: AuthUserModel | None) -> AuthUser | None:
        if model is None:
            return None
        return AuthUser(
            email=model.email,
            full_name=model.full_name,
            phone_encrypted=model.phone_encrypted,
            birth_date_encrypted=model.birth_date_encrypted,
            password_hash=model.password_hash,
            role=model.role,
            is_verified=model.is_verified == "true",
            verification_code_encrypted=model.verification_code_encrypted,
            verification_code_expires_at=self._normalize_datetime(model.verification_code_expires_at),
            reset_code_encrypted=model.reset_code_encrypted,
            reset_code_expires_at=self._normalize_datetime(model.reset_code_expires_at),
            created_at=self._normalize_datetime(model.created_at) or datetime.now(UTC),
        )

    def _send_verification_code(self, user: AuthUser, code: str) -> None:
        self._email_service.send_code(
            to_email=user.email,
            subject="SmartLocker: подтверждение email",
            heading="Подтверждение email",
            code=code,
            body="Введите этот код на странице подтверждения SmartLocker.",
        )

    def _send_reset_code(self, user: AuthUser, code: str) -> None:
        self._email_service.send_code(
            to_email=user.email,
            subject="SmartLocker: сброс пароля",
            heading="Сброс пароля",
            code=code,
            body="Введите этот код на странице восстановления пароля и задайте новый пароль.",
        )

    def _decrypt_optional(self, value: str | None) -> str | None:
        if not value:
            return None
        return self._encryption.decrypt(value)

    def _decrypt_phone(self, user: AuthUser) -> str:
        return self._encryption.decrypt(user.phone_encrypted)

    def _decrypt_birth_date(self, user: AuthUser) -> date:
        return date.fromisoformat(self._encryption.decrypt(user.birth_date_encrypted))

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120_000,
        )
        return f"{salt}${digest.hex()}"

    @staticmethod
    def _verify_password(password: str, stored_hash: str) -> bool:
        salt, password_hash = stored_hash.split("$", maxsplit=1)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120_000,
        ).hex()
        return hmac.compare_digest(digest, password_hash)

    @staticmethod
    def _calculate_age(birth_date: date) -> int:
        today = date.today()
        return today.year - birth_date.year - (
            (today.month, today.day) < (birth_date.month, birth_date.day)
        )
