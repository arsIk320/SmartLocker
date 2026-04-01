from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class RecipientRef:
    user_id: str
    chat_id: str | None = None


class MaxPlatformClient:
    def __init__(self, *, token: str, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": token}

    async def get_updates(
        self,
        *,
        marker: int | None,
        timeout: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "timeout": timeout,
            "limit": 100,
            "types": ["message_created", "bot_started"],
        }
        if marker is not None:
            params["marker"] = marker
        async with httpx.AsyncClient(timeout=timeout + 10, trust_env=False) as client:
            response = await client.get(
                f"{self._base_url}/updates",
                headers=self._headers,
                params=params,
            )
        response.raise_for_status()
        return response.json()

    async def send_message(
        self,
        *,
        recipient: RecipientRef,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        params = {"chat_id": recipient.chat_id} if recipient.chat_id else {"user_id": recipient.user_id}
        body: dict[str, Any] = {"text": text, "notify": True}
        if attachments:
            body["attachments"] = attachments
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.post(
                f"{self._base_url}/messages",
                headers={**self._headers, "Content-Type": "application/json"},
                params=params,
                json=body,
            )
        response.raise_for_status()
        return response.json()

    async def upload_image(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.post(
                f"{self._base_url}/uploads",
                headers=self._headers,
                params={"type": "image"},
            )
            response.raise_for_status()
            upload_url = response.json()["url"]
            upload_response = await client.post(
                upload_url,
                headers=self._headers,
                files={"data": (filename, content, content_type)},
            )
        upload_response.raise_for_status()
        return upload_response.json()

    async def download_binary(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, trust_env=False) as client:
            response = await client.get(url, headers=self._headers)
            if response.status_code in {401, 403}:
                response = await client.get(url)
        response.raise_for_status()
        return response.content
