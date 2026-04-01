from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.domain import Reservation


class TravelLineConnectionConfig(BaseModel):
    client_id: str
    client_secret: str
    property_id: str
    auth_url: str
    api_base_url: str
    timeout_seconds: int = 20


class TravelLineConfigStatus(BaseModel):
    configured: bool
    api_base_url: str
    auth_url: str
    has_client_id: bool
    has_client_secret: bool
    has_property_id: bool


class TravelLineSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_modification: datetime | None = None
    continue_token: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)

    @field_validator("continue_token", mode="before")
    @classmethod
    def normalize_continue_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized or normalized.lower() == "string":
                return None
            return normalized
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "TravelLineSyncRequest":
        if self.continue_token and self.last_modification:
            raise ValueError(
                "continue_token and last_modification cannot be used together."
            )
        return self


class TravelLineSyncResponse(BaseModel):
    provider: str
    fetched: int
    reservations: list[Reservation]
    next_page_token: str | None = None
    has_more_data: bool = False
