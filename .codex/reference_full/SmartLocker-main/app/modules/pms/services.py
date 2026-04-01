from app.core.config import Settings
from app.modules.pms.connection_service import TravelLineUserConnection
from app.modules.pms.providers.travelline import TravelLineClient
from app.modules.pms.schemas.travelline import (
    TravelLineConnectionConfig,
    TravelLineSyncRequest,
    TravelLineSyncResponse,
)


class TravelLineSyncService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def sync_reservations(
        self,
        payload: TravelLineSyncRequest,
        connection: TravelLineConnectionConfig | None = None,
    ) -> TravelLineSyncResponse:
        if connection is None and (
            not self._settings.travelline_client_id
            or not self._settings.travelline_client_secret
            or not self._settings.travelline_property_id
        ):
            raise ValueError("TravelLine credentials or property id are not configured.")

        async with TravelLineClient(settings=self._settings, connection=connection) as client:
            reservations, next_page_token, has_more_data = await client.fetch_reservations(payload)

        return TravelLineSyncResponse(
            provider="travelline",
            fetched=len(reservations),
            reservations=reservations,
            next_page_token=next_page_token,
            has_more_data=has_more_data,
        )

    async def fetch_properties_catalog(
        self,
        connection: TravelLineConnectionConfig,
    ) -> list[dict[str, object]]:
        async with TravelLineClient(settings=self._settings, connection=connection) as client:
            return await client.fetch_properties_catalog()
