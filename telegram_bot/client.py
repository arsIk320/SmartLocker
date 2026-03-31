from __future__ import annotations

from io import BytesIO

import httpx


class SmartLockerTelegramApiClient:
    def __init__(self, *, api_base_url: str, api_key: str) -> None:
        self._api_base_url = api_base_url.rstrip("/")
        self._headers = {"X-Bot-Api-Key": api_key}

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = None
            try:
                payload = response.json()
                detail = payload.get("detail")
            except Exception:
                detail = None
            if detail:
                raise RuntimeError(str(detail)) from exc
            raise

    async def search_guest_bookings(
        self,
        *,
        guest_query: str,
    ) -> dict:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(
                f"{self._api_base_url}/api/v1/telegram/guest/bookings",
                headers=self._headers,
                data={"guest_query": guest_query},
            )
        self._raise_for_status(response)
        return response.json()

    async def get_bound_bookings(
        self,
        *,
        telegram_chat_id: str,
    ) -> dict:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(
                f"{self._api_base_url}/api/v1/telegram/guest/bindings",
                headers=self._headers,
                data={"telegram_chat_id": telegram_chat_id},
            )
        self._raise_for_status(response)
        return response.json()

    async def bind_booking(
        self,
        *,
        reservation_code: str,
        telegram_chat_id: str,
    ) -> dict:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(
                f"{self._api_base_url}/api/v1/telegram/guest/bind",
                headers=self._headers,
                data={
                    "reservation_code": reservation_code,
                    "telegram_chat_id": telegram_chat_id,
                },
            )
        self._raise_for_status(response)
        return response.json()

    async def lookup_guest_access(
        self,
        *,
        reservation_code: str,
    ) -> dict:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(
                f"{self._api_base_url}/api/v1/telegram/guest/access",
                headers=self._headers,
                data={"reservation_code": reservation_code},
            )
        self._raise_for_status(response)
        return response.json()

    async def upload_face_photo(
        self,
        *,
        reservation_code: str,
        guest_query: str,
        telegram_chat_id: str,
        content: bytes,
        filename: str = "face.jpg",
        content_type: str = "image/jpeg",
    ) -> dict:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            response = await client.post(
                f"{self._api_base_url}/api/v1/telegram/guest/face-photo",
                headers=self._headers,
                data={
                    "reservation_code": reservation_code,
                    "guest_query": guest_query,
                    "telegram_chat_id": telegram_chat_id,
                },
                files={"photo": (filename, BytesIO(content), content_type)},
            )
        self._raise_for_status(response)
        return response.json()
