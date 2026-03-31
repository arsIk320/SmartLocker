from __future__ import annotations

import httpx


class SmartLockerApiClient:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, trust_env=False)
        self._token: str | None = None

    def set_token(self, token: str | None) -> None:
        self._token = token

    def login(self, email: str, password: str) -> dict:
        response = self._client.post(
            "/api/v1/client/auth/login",
            json={"email": email, "password": password},
        )
        self._raise_for_error(response)
        payload = response.json()
        self._token = payload["access_token"]
        return payload

    def me(self) -> dict:
        response = self._client.get("/api/v1/client/auth/me", headers=self._auth_headers())
        self._raise_for_error(response)
        return response.json()["user"]

    def list_objects(self) -> list[dict]:
        response = self._client.get("/api/v1/client/objects", headers=self._auth_headers())
        self._raise_for_error(response)
        return response.json()["houses"]

    def create_house(self, name: str, address: str) -> dict:
        response = self._client.post(
            "/api/v1/client/objects/houses",
            headers=self._auth_headers(),
            json={"name": name, "address": address},
        )
        self._raise_for_error(response)
        return response.json()["house"]

    def create_door(
        self,
        *,
        house_id: str,
        name: str,
        lock_label: str,
        travelline_unit_id: str = "",
    ) -> dict:
        response = self._client.post(
            "/api/v1/client/objects/doors",
            headers=self._auth_headers(),
            json={
                "house_id": house_id,
                "name": name,
                "lock_label": lock_label,
                "travelline_unit_id": travelline_unit_id or None,
            },
        )
        self._raise_for_error(response)
        return response.json()["door"]

    def bind_lock(self, door_id: str, lock_uid: str) -> dict:
        response = self._client.post(
            f"/api/v1/client/doors/{door_id}/bind-lock",
            headers=self._auth_headers(),
            json={"lock_uid": lock_uid},
        )
        self._raise_for_error(response)
        return response.json()

    def list_locks(self) -> list[dict]:
        response = self._client.get("/api/v1/client/locks", headers=self._auth_headers())
        self._raise_for_error(response)
        return response.json()["devices"]

    def save_lock(
        self,
        *,
        lock_id: str,
        device_name: str,
        wifi_ssid: str,
        wifi_password: str,
        port_name: str = "",
        door_id: str | None = None,
        esp8266_uid: str = "",
        esp32_uid: str = "",
    ) -> dict:
        response = self._client.post(
            "/api/v1/client/locks",
            headers=self._auth_headers(),
            json={
                "lock_id": lock_id,
                "device_name": device_name,
                "wifi_ssid": wifi_ssid,
                "wifi_password": wifi_password,
                "port_name": port_name,
                "door_id": door_id,
                "esp8266_uid": esp8266_uid,
                "esp32_uid": esp32_uid,
            },
        )
        self._raise_for_error(response)
        return response.json()

    def health(self) -> dict:
        response = self._client.get("/health")
        self._raise_for_error(response)
        return response.json()

    def get_lock_current_qr(self, *, lock_id: str, api_key: str) -> dict:
        response = self._client.get(
            "/api/v1/locks/qr/current",
            headers={
                "X-Lock-Id": lock_id,
                "X-Lock-Api-Key": api_key,
            },
        )
        self._raise_for_error(response)
        return response.json()

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            raise RuntimeError("Не выполнена авторизация в SmartLocker API.")
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                payload = response.json()
                detail = payload.get("detail") or ""
            except Exception:
                detail = response.text
            message = detail or str(exc)
            raise RuntimeError(message) from exc
