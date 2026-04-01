from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import TravelLineConnectionModel
from app.services.encryption import EncryptionService


@dataclass
class TravelLineUserConnection:
    owner_email: str
    client_id: str
    client_secret_encrypted: str
    property_ids_encrypted: str
    auth_url: str
    api_base_url: str


class TravelLineConnectionService:
    def __init__(self, db: Session, encryption: EncryptionService) -> None:
        self._db = db
        self._encryption = encryption

    def save_connection(
        self,
        *,
        owner_email: str,
        client_id: str,
        client_secret: str,
        property_ids: list[str],
        auth_url: str,
        api_base_url: str,
    ) -> TravelLineConnectionModel:
        normalized_email = owner_email.strip().lower()
        normalized_property_ids = [item.strip() for item in property_ids if item.strip()]
        if not normalized_property_ids:
            raise ValueError("Укажите хотя бы один Property ID TravelLine.")

        connection = self.get_connection(normalized_email)
        if connection is None:
            connection = TravelLineConnectionModel(owner_email=normalized_email)
            self._db.add(connection)

        connection.client_id = client_id.strip()
        connection.client_secret_encrypted = self._encryption.encrypt(client_secret.strip())
        connection.property_ids_encrypted = self._encryption.encrypt(
            ",".join(normalized_property_ids)
        )
        connection.auth_url = auth_url.strip()
        connection.api_base_url = api_base_url.strip()
        self._db.commit()
        self._db.refresh(connection)
        return connection

    def get_connection(self, owner_email: str) -> TravelLineConnectionModel | None:
        return (
            self._db.query(TravelLineConnectionModel)
            .filter(TravelLineConnectionModel.owner_email == owner_email.strip().lower())
            .one_or_none()
        )

    def list_connections(self) -> list[TravelLineConnectionModel]:
        return (
            self._db.query(TravelLineConnectionModel)
            .order_by(TravelLineConnectionModel.created_at.asc())
            .all()
        )

    def export_view(self, owner_email: str) -> dict[str, str] | None:
        connection = self.get_connection(owner_email)
        if connection is None:
            return None
        return {
            "client_id": connection.client_id,
            "property_ids": ", ".join(self.decrypt_property_ids(connection)),
            "auth_url": connection.auth_url,
            "api_base_url": connection.api_base_url,
        }

    def decrypt_secret(self, connection: TravelLineConnectionModel) -> str:
        return self._encryption.decrypt(connection.client_secret_encrypted)

    def decrypt_property_ids(self, connection: TravelLineConnectionModel) -> list[str]:
        return [
            item.strip()
            for item in self._encryption.decrypt(connection.property_ids_encrypted).split(",")
            if item.strip()
        ]
