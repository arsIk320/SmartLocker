from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class UserRead(BaseModel):
    uuid: str
    name: str
    enabled: bool
    created_at: datetime
    vless_url: str

    model_config = {"from_attributes": True}


class UserConnection(BaseModel):
    uuid: str
    name: str
    server: str
    port: int
    vless_url: str


class DomainList(BaseModel):
    domains: list[str]


class ServiceStatus(BaseModel):
    xray_active: bool
    manager_active: bool
    config_ok: bool
    users: int
    domains: int
