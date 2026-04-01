from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ReservationStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    checked_in = "checked_in"
    checked_out = "checked_out"


class Guest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    name: str
    phone: str | None = None
    email: str | None = None


class Reservation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    external_id: str
    provider: str
    unit_external_id: str | None = None
    guest_name: str
    guest_phone: str | None = None
    check_in: datetime
    check_out: datetime
    status: ReservationStatus = ReservationStatus.confirmed
