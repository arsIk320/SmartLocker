from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import TravelLineConnectionModel
from app.models.domain import Reservation
from app.modules.pms.connection_service import TravelLineConnectionService
from app.modules.pms.schemas.travelline import TravelLineConnectionConfig, TravelLineSyncRequest
from app.modules.pms.services import TravelLineSyncService
from app.modules.properties.service import PropertyService
from app.services.encryption import EncryptionService

logger = logging.getLogger(__name__)


class TravelLineGrantSyncService:
    def __init__(
        self,
        *,
        settings: Settings,
        db: Session,
        encryption: EncryptionService,
    ) -> None:
        self._settings = settings
        self._db = db
        self._encryption = encryption
        self._connection_service = TravelLineConnectionService(db=db, encryption=encryption)
        self._property_service = PropertyService(db=db, encryption=encryption)
        self._sync_service = TravelLineSyncService(settings=settings)

    async def sync_all_connections(self) -> int:
        total_synced = 0
        for connection in self._connection_service.list_connections():
            try:
                synced_count, _ = await self._sync_connection(connection=connection)
                total_synced += synced_count
            except Exception:
                logger.exception(
                    "Failed to sync TravelLine connection for owner %s",
                    connection.owner_email,
                )
        return total_synced

    async def sync_owner_connection(self, *, owner_email: str) -> list[Reservation]:
        connection = self._connection_service.get_connection(owner_email)
        if connection is None:
            return []
        _, reservations = await self._sync_connection(connection=connection)
        return reservations

    async def _sync_connection(
        self,
        *,
        connection: TravelLineConnectionModel,
    ) -> tuple[int, list[Reservation]]:
        property_ids = self._connection_service.decrypt_property_ids(connection)
        if not property_ids:
            return 0, []

        base_connection = TravelLineConnectionConfig(
            client_id=connection.client_id,
            client_secret=self._connection_service.decrypt_secret(connection),
            property_id=property_ids[0],
            auth_url=connection.auth_url,
            api_base_url=connection.api_base_url,
            timeout_seconds=self._settings.travelline_timeout_seconds,
        )
        catalog = await self._sync_service.fetch_properties_catalog(base_connection)
        self._property_service.sync_houses_from_travelline(
            owner_email=connection.owner_email,
            properties=catalog,
        )

        reservations: list[Reservation] = []
        for property_id in property_ids:
            current_connection = TravelLineConnectionConfig(
                client_id=connection.client_id,
                client_secret=base_connection.client_secret,
                property_id=property_id,
                auth_url=connection.auth_url,
                api_base_url=connection.api_base_url,
                timeout_seconds=self._settings.travelline_timeout_seconds,
            )
            continue_token: str | None = None
            for _ in range(self._settings.travelline_auto_sync_max_pages):
                result = await self._sync_service.sync_reservations(
                    payload=TravelLineSyncRequest(
                        limit=self._settings.travelline_auto_sync_limit_per_page,
                        continue_token=continue_token,
                    ),
                    connection=current_connection,
                )
                reservations.extend(result.reservations)
                if not result.has_more_data or not result.next_page_token:
                    break
                continue_token = result.next_page_token

        self._property_service.sync_access_grants(
            owner_email=connection.owner_email,
            reservations=reservations,
        )
        return len(reservations), reservations
