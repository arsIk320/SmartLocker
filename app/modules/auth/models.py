from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class AuthUser:
    email: str
    full_name: str
    phone_encrypted: str
    birth_date_encrypted: str
    password_hash: str
    role: str = "user"
    is_verified: bool = False
    verification_code_encrypted: str | None = None
    verification_code_expires_at: datetime | None = None
    reset_code_encrypted: str | None = None
    reset_code_expires_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
