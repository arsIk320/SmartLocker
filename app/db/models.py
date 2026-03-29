from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class TravelLineConnectionModel(Base):
    __tablename__ = "travelline_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(255))
    client_secret_encrypted: Mapped[str] = mapped_column(String(4096))
    property_ids_encrypted: Mapped[str] = mapped_column(String(4096))
    auth_url: Mapped[str] = mapped_column(String(512))
    api_base_url: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuthUserModel(Base):
    __tablename__ = "auth_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    phone_encrypted: Mapped[str] = mapped_column(String(4096))
    birth_date_encrypted: Mapped[str] = mapped_column(String(4096))
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(32), default="user")
    is_verified: Mapped[str] = mapped_column(String(8), default="false")
    verification_code_encrypted: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    verification_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reset_code_encrypted: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    reset_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class HouseModel(Base):
    __tablename__ = "houses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(255))
    address_encrypted: Mapped[str] = mapped_column(String(4096))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    doors: Mapped[list[DoorModel]] = relationship(
        back_populates="house",
        cascade="all, delete-orphan",
        order_by="DoorModel.created_at",
    )


class DoorModel(Base):
    __tablename__ = "doors"
    __table_args__ = (
        UniqueConstraint("house_id", "name", name="uq_house_door_name"),
        UniqueConstraint("door_uid", name="uq_door_uid"),
        UniqueConstraint("lock_uid_hash", name="uq_lock_uid_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    door_uid: Mapped[str] = mapped_column(String(32), index=True)
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    house_id: Mapped[str] = mapped_column(String(36), ForeignKey("houses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    lock_label_encrypted: Mapped[str] = mapped_column(String(4096))
    lock_uid_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lock_uid_encrypted: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    qr_secret_encrypted: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    qr_secret_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    travelline_unit_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    house: Mapped[HouseModel] = relationship(back_populates="doors")
    access_grants: Mapped[list[AccessGrantModel]] = relationship(
        back_populates="door",
        cascade="all, delete-orphan",
        order_by="AccessGrantModel.valid_from",
    )
    lock_devices: Mapped[list["LockDeviceModel"]] = relationship(
        back_populates="door",
        order_by="LockDeviceModel.updated_at.desc()",
    )


class AccessGrantModel(Base):
    __tablename__ = "access_grants"
    __table_args__ = (
        UniqueConstraint("reservation_external_id", "door_id", name="uq_reservation_door_grant"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    reservation_external_id: Mapped[str] = mapped_column(String(255), index=True)
    door_id: Mapped[str] = mapped_column(String(36), ForeignKey("doors.id", ondelete="CASCADE"), index=True)
    guest_name_encrypted: Mapped[str] = mapped_column(String(4096))
    method: Mapped[str] = mapped_column(String(32), default="pin")
    status: Mapped[str] = mapped_column(String(32), default="active")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    door: Mapped[DoorModel] = relationship(back_populates="access_grants")


class LockDeviceModel(Base):
    __tablename__ = "lock_devices"
    __table_args__ = (
        UniqueConstraint("lock_id_hash", name="uq_lock_devices_lock_id_hash"),
        UniqueConstraint("device_uid_hash", name="uq_lock_devices_uid_hash"),
        UniqueConstraint("api_key_hash", name="uq_lock_devices_api_key_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    door_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("doors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    lock_id_hash: Mapped[str] = mapped_column(String(128), index=True)
    lock_id_encrypted: Mapped[str] = mapped_column(String(4096))
    api_key_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    device_uid_hash: Mapped[str] = mapped_column(String(128), index=True)
    device_uid_encrypted: Mapped[str] = mapped_column(String(4096))
    esp8266_uid_encrypted: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    esp32_uid_encrypted: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    device_name_encrypted: Mapped[str] = mapped_column(String(4096))
    wifi_ssid_encrypted: Mapped[str] = mapped_column(String(4096))
    wifi_password_encrypted: Mapped[str] = mapped_column(String(4096))
    port_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="configured")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    door: Mapped[DoorModel | None] = relationship(back_populates="lock_devices")
