from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import Settings
from app.models.domain import Reservation, ReservationStatus
from app.modules.pms.schemas.travelline import (
    TravelLineConnectionConfig,
    TravelLineSyncRequest,
)


class TravelLineClient:
    def __init__(
        self,
        settings: Settings,
        connection: TravelLineConnectionConfig | None = None,
    ) -> None:
        self._settings = settings
        self._connection = connection
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None

    async def __aenter__(self) -> "TravelLineClient":
        self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
        self._access_token = await self._get_access_token()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def fetch_reservations(
        self,
        payload: TravelLineSyncRequest,
    ) -> tuple[list[Reservation], str | None, bool]:
        client = self._require_client()
        headers = {"Authorization": f"Bearer {self._require_access_token()}"}
        params = self._build_search_params(payload)
        property_id = self._property_id

        try:
            response = await client.get(
                f"{self._api_base_url.rstrip('/')}/api/read-reservation/v1/properties/{property_id}/bookings",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(self._format_http_error("TravelLine search", exc)) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("Unable to reach TravelLine API.") from exc

        search_payload = response.json()
        reservation_items = search_payload.get("bookingSummaries", [])
        if not isinstance(reservation_items, list):
            raise RuntimeError("Unexpected TravelLine search payload format.")

        normalized: list[Reservation] = []
        for item in reservation_items[: payload.limit]:
            number = item.get("number")
            if not number:
                continue
            detail_payload = await self._fetch_reservation_details(str(number), headers)
            normalized.append(self._map_reservation_detail(detail_payload))

        return (
            normalized,
            search_payload.get("continueToken"),
            bool(search_payload.get("hasMoreData", False)),
        )

    async def fetch_properties_catalog(self) -> list[dict[str, Any]]:
        client = self._require_client()
        headers = {"Authorization": f"Bearer {self._require_access_token()}"}
        try:
            response = await client.get(
                f"{self._api_base_url.rstrip('/')}/api/content/v1/properties",
                params={"count": 200},
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(self._format_http_error("TravelLine content list", exc)) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("Unable to fetch TravelLine properties.") from exc

        payload = response.json()
        property_items = payload.get("properties", [])
        if not isinstance(property_items, list):
            raise RuntimeError("Unexpected TravelLine content list payload.")

        catalog: list[dict[str, Any]] = []
        for item in property_items:
            property_id = str(item.get("id", "")).strip()
            if not property_id:
                continue
            detail = await self._fetch_property_detail(property_id, headers)
            catalog.append(self._map_property_detail(detail))
        return catalog

    async def _get_access_token(self) -> str:
        client = self._require_client()
        try:
            response = await client.post(
                self._auth_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(self._format_http_error("TravelLine auth", exc)) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("Unable to authenticate with TravelLine.") from exc

        payload = response.json()
        access_token = payload.get("access_token")
        if not access_token:
            raise RuntimeError("TravelLine auth response does not contain access_token.")
        return str(access_token)

    async def _fetch_reservation_details(
        self,
        reservation_number: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        client = self._require_client()
        try:
            response = await client.get(
                f"{self._api_base_url.rstrip('/')}/api/read-reservation/v1/properties/{self._property_id}/bookings/{reservation_number}",
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                self._format_http_error(
                    f"TravelLine reservation details for {reservation_number}",
                    exc,
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("Unable to fetch TravelLine reservation details.") from exc

        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected TravelLine reservation details payload.")
        return payload

    async def _fetch_property_detail(
        self,
        property_id: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        client = self._require_client()
        try:
            response = await client.get(
                f"{self._api_base_url.rstrip('/')}/api/content/v1/properties/{property_id}",
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                self._format_http_error(f"TravelLine property details for {property_id}", exc)
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("Unable to fetch TravelLine property details.") from exc

        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected TravelLine property details payload.")
        return payload

    @staticmethod
    def _build_search_params(payload: TravelLineSyncRequest) -> dict[str, Any]:
        if payload.continue_token:
            return {"continueToken": payload.continue_token, "count": payload.limit}

        params: dict[str, Any] = {"count": payload.limit}
        if payload.last_modification:
            params["lastModification"] = payload.last_modification.astimezone(UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        return params

    @staticmethod
    def _map_reservation_detail(payload: dict[str, Any]) -> Reservation:
        reservation = TravelLineClient._extract_reservation(payload)
        if not isinstance(reservation, dict):
            keys = ", ".join(sorted(payload.keys()))
            raise RuntimeError(
                "TravelLine reservation payload does not contain reservation. "
                f"Available keys: {keys or '<empty>'}."
            )

        room_stays = reservation.get("roomStays", [])
        first_room_stay = room_stays[0] if isinstance(room_stays, list) and room_stays else {}
        customer = reservation.get("customer", {})

        stay_dates = first_room_stay.get("stayDates", {}) if isinstance(first_room_stay, dict) else {}
        check_in = TravelLineClient._pick_datetime(
            stay_dates,
            "checkInDateTime",
            "arrivalDateTime",
        )
        check_out = TravelLineClient._pick_datetime(
            stay_dates,
            "checkOutDateTime",
            "departureDateTime",
        )
        if not check_in:
            check_in = TravelLineClient._pick_datetime(
                first_room_stay,
                "checkInDateTime",
                "arrivalDateTime",
                "plannedArrivalDateTime",
            )
        if not check_out:
            check_out = TravelLineClient._pick_datetime(
                first_room_stay,
                "checkOutDateTime",
                "departureDateTime",
                "plannedDepartureDateTime",
            )

        if not check_in or not check_out:
            raise RuntimeError("TravelLine reservation detail is missing stay dates.")

        guest_name = TravelLineClient._format_guest_name(customer)
        phone = TravelLineClient._pick_nested(
            customer,
            ("contacts", 0, "phone"),
            ("contacts", 0, "value"),
            ("phone",),
            default=None,
        )

        return Reservation(
            external_id=str(reservation.get("number", "")),
            provider="travelline",
            unit_external_id=TravelLineClient._pick_nested(
                first_room_stay,
                ("roomType", "id"),
                ("roomTypeId",),
                ("roomId",),
                default=None,
            ),
            guest_name=guest_name or "Unknown guest",
            guest_phone=str(phone) if phone else None,
            check_in=check_in,
            check_out=check_out,
            status=TravelLineClient._map_status(
                str(
                    reservation.get(
                        "reservationStatus",
                        reservation.get("status", "Active"),
                    )
                )
            ),
        )

    @staticmethod
    def _extract_reservation(payload: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None

        for key in ("reservation", "booking", "bookingDetails", "data"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value

        if any(
            key in payload
            for key in ("number", "roomStays", "customer", "reservationStatus", "status")
        ):
            return payload

        return None

    @staticmethod
    def _map_property_detail(payload: dict[str, Any]) -> dict[str, Any]:
        contact_info = payload.get("contactInfo", {}) if isinstance(payload, dict) else {}
        address = contact_info.get("address", {}) if isinstance(contact_info, dict) else {}
        address_parts = [
            str(address.get("countryCode", "")).strip(),
            str(address.get("region", "")).strip(),
            str(address.get("cityName", "")).strip(),
            str(address.get("addressLine", "")).strip(),
        ]
        room_types = payload.get("roomTypes", [])
        normalized_room_types: list[dict[str, str]] = []
        if isinstance(room_types, list):
            for room_type in room_types:
                if not isinstance(room_type, dict):
                    continue
                room_type_id = str(room_type.get("id", "")).strip()
                if not room_type_id:
                    continue
                normalized_room_types.append(
                    {
                        "id": room_type_id,
                        "name": str(room_type.get("name", f"Room Type {room_type_id}")).strip(),
                    }
                )

        return {
            "id": str(payload.get("id", "")).strip(),
            "name": str(payload.get("name", "Объект TravelLine")).strip(),
            "address": ", ".join(part for part in address_parts if part),
            "room_types": normalized_room_types,
        }

    @staticmethod
    def _format_guest_name(customer: Any) -> str:
        if not isinstance(customer, dict):
            return ""

        first_name = str(customer.get("firstName", "")).strip()
        last_name = str(customer.get("lastName", "")).strip()
        middle_name = str(customer.get("middleName", "")).strip()
        full_name = " ".join(part for part in [last_name, first_name, middle_name] if part)
        if full_name:
            return full_name
        return str(customer.get("displayName", "")).strip()

    @staticmethod
    def _pick_datetime(source: Any, *keys: str) -> datetime | None:
        if not isinstance(source, dict):
            return None
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value:
                normalized = value.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(normalized)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed
        return None

    @staticmethod
    def _pick_nested(source: Any, *paths: tuple[Any, ...], default: Any) -> Any:
        for path in paths:
            current = source
            for part in path:
                if isinstance(part, int):
                    if not isinstance(current, list) or len(current) <= part:
                        current = None
                        break
                    current = current[part]
                else:
                    if not isinstance(current, dict) or part not in current:
                        current = None
                        break
                    current = current[part]
            if current is not None:
                return current
        return default

    @staticmethod
    def _map_status(value: str) -> ReservationStatus:
        normalized = value.strip().lower()
        mapping = {
            "active": ReservationStatus.confirmed,
            "confirmed": ReservationStatus.confirmed,
            "unconfirmed": ReservationStatus.pending,
            "new": ReservationStatus.pending,
            "pending": ReservationStatus.pending,
            "cancelled": ReservationStatus.cancelled,
            "canceled": ReservationStatus.cancelled,
            "checkedin": ReservationStatus.checked_in,
            "checkedout": ReservationStatus.checked_out,
        }
        return mapping.get(normalized, ReservationStatus.confirmed)

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("TravelLine client is not initialized.")
        return self._client

    def _require_access_token(self) -> str:
        if self._access_token is None:
            raise RuntimeError("TravelLine access token is not initialized.")
        return self._access_token

    @property
    def _client_id(self) -> str:
        return (
            self._connection.client_id
            if self._connection is not None
            else (self._settings.travelline_client_id or "")
        )

    @property
    def _client_secret(self) -> str:
        return (
            self._connection.client_secret
            if self._connection is not None
            else (self._settings.travelline_client_secret or "")
        )

    @property
    def _property_id(self) -> str:
        return (
            self._connection.property_id
            if self._connection is not None
            else (self._settings.travelline_property_id or "")
        )

    @property
    def _auth_url(self) -> str:
        return (
            self._connection.auth_url
            if self._connection is not None
            else self._settings.travelline_auth_url
        )

    @property
    def _api_base_url(self) -> str:
        return (
            self._connection.api_base_url
            if self._connection is not None
            else self._settings.travelline_api_base_url
        )

    @property
    def _timeout_seconds(self) -> int:
        return (
            self._connection.timeout_seconds
            if self._connection is not None
            else self._settings.travelline_timeout_seconds
        )

    @staticmethod
    def _format_http_error(context: str, exc: httpx.HTTPStatusError) -> str:
        response = exc.response
        detail = TravelLineClient._extract_error_text(response)
        if detail:
            return (
                f"{context} responded with HTTP {response.status_code}. "
                f"TravelLine response: {detail}"
            )
        return f"{context} responded with HTTP {response.status_code}."

    @staticmethod
    def _extract_error_text(response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text[:500] if text else None

        if isinstance(payload, dict):
            for key in ("message", "error", "error_description", "detail", "title"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

            errors = payload.get("errors")
            if isinstance(errors, list):
                parts: list[str] = []
                for item in errors:
                    if isinstance(item, str) and item.strip():
                        parts.append(item.strip())
                    elif isinstance(item, dict):
                        text = next(
                            (
                                str(item.get(field)).strip()
                                for field in ("message", "error", "detail", "description")
                                if item.get(field)
                            ),
                            "",
                        )
                        if text:
                            parts.append(text)
                if parts:
                    return "; ".join(parts)[:500]

        if isinstance(payload, list):
            parts = [str(item).strip() for item in payload if str(item).strip()]
            if parts:
                return "; ".join(parts)[:500]

        text = response.text.strip()
        return text[:500] if text else None
