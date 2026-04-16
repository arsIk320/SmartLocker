from __future__ import annotations

import json
import re
import secrets
import subprocess
import time
from dataclasses import dataclass

import serial
from serial.tools import list_ports


@dataclass
class SerialBoardInfo:
    port: str
    description: str
    hwid: str
    chip: str | None = None
    firmware_version: str | None = None
    board_uid: str | None = None
    protocol: str | None = None


class SerialProvisioningService:
    """Provision ESP boards over a simple newline-delimited JSON serial protocol."""

    PROTOCOL_NAME = "smartlocker-provisioning-v1"
    READ_POLL_TIMEOUT = 0.25
    PREPARE_DELAY_SECONDS = 0.35
    SUPPORTED_CHIPS = {"ESP32", "ESP32-CAM"}
    ESP32_FAMILY = {"ESP32", "ESP32-CAM"}

    def list_ports(self) -> list[SerialBoardInfo]:
        ports = []
        for item in sorted(list_ports.comports(), key=lambda port: port.device):
            ports.append(
                SerialBoardInfo(
                    port=item.device,
                    description=item.description or item.name or item.device,
                    hwid=item.hwid or "",
                )
            )
        return ports

    def list_wifi_networks(self) -> list[str]:
        try:
            result = subprocess.run(
                ["netsh", "wlan", "show", "networks", "mode=bssid"],
                capture_output=True,
                timeout=10,
                check=True,
            )
        except Exception:
            return []

        pattern = re.compile(r"^\s*SSID\s+\d+\s*:\s*(.*)$", re.IGNORECASE)
        networks: list[str] = []
        stdout = result.stdout.decode("utf-8", errors="ignore")
        if not stdout.strip():
            stdout = result.stdout.decode("cp866", errors="ignore")
        for line in stdout.splitlines():
            match = pattern.match(line)
            if not match:
                continue
            ssid = match.group(1).strip()
            if ssid and ssid not in networks:
                networks.append(ssid)
        return networks

    def identify_board(self, port_name: str, *, baudrate: int = 9600, timeout: float = 3.0) -> SerialBoardInfo:
        port_info = self._lookup_port(port_name)
        with self._open_connection(port_name=port_name, baudrate=baudrate, timeout=timeout) as connection:
            self._prepare_connection(connection)
            response = self._request(
                connection,
                {
                    "action": "identify",
                    "protocol": self.PROTOCOL_NAME,
                },
                timeout=timeout,
                attempts=3,
            )

        chip = str(response.get("chip", "")).strip().upper()
        if chip not in self.SUPPORTED_CHIPS:
            raise ValueError("Подключенная плата не ответила корректным типом chip.")

        return SerialBoardInfo(
            port=port_name,
            description=port_info.description,
            hwid=port_info.hwid,
            chip=chip,
            firmware_version=str(response.get("firmware_version", "")).strip() or None,
            board_uid=str(response.get("board_uid", "")).strip() or None,
            protocol=str(response.get("protocol", "")).strip() or None,
        )

    def provision_board(
        self,
        *,
        port_name: str,
        chip: str,
        lock_id: str,
        board_uid: str,
        device_name: str,
        wifi_ssid: str,
        wifi_password: str,
        owner_email: str,
        door_uid: str = "",
        api_key: str = "",
        api_base_url: str = "",
        baudrate: int = 9600,
        timeout: float = 5.0,
    ) -> dict[str, object]:
        normalized_chip = chip.strip().upper()
        if normalized_chip not in self.SUPPORTED_CHIPS:
            raise ValueError("Для записи конфигурации нужен chip ESP32 или ESP32-CAM.")

        payload = {
            "action": "provision",
            "protocol": self.PROTOCOL_NAME,
            "payload": {
                "chip": normalized_chip,
                "lock_id": lock_id,
                "board_uid": board_uid,
                "device_name": device_name,
                "wifi_ssid": wifi_ssid,
                "wifi_password": wifi_password,
                "owner_email": owner_email,
                "door_uid": door_uid,
                "api_key": api_key,
                "api_base_url": api_base_url,
            },
        }

        with self._open_connection(port_name=port_name, baudrate=baudrate, timeout=timeout) as connection:
            self._prepare_connection(connection)
            return self._request(connection, payload, timeout=timeout, attempts=3)

    @staticmethod
    def generate_lock_id() -> str:
        return f"LOCK-{secrets.token_hex(4).upper()}"

    @staticmethod
    def generate_board_uid(chip: str) -> str:
        normalized_chip = chip.strip().upper()
        if normalized_chip == "ESP32-CAM":
            prefix = "ESP32CAM"
        elif normalized_chip in SerialProvisioningService.ESP32_FAMILY:
            prefix = "ESP32"
        else:
            prefix = "ESP32"
        return f"{prefix}-{secrets.token_hex(4).upper()}"

    def _lookup_port(self, port_name: str) -> SerialBoardInfo:
        for item in self.list_ports():
            if item.port == port_name:
                return item
        return SerialBoardInfo(port=port_name, description=port_name, hwid="")

    def _open_connection(self, *, port_name: str, baudrate: int, timeout: float) -> serial.Serial:
        read_timeout = min(self.READ_POLL_TIMEOUT, max(timeout, 0.1))
        return serial.Serial(
            port=port_name,
            baudrate=baudrate,
            timeout=read_timeout,
            write_timeout=max(timeout, 1.0),
        )

    def _request(
        self,
        connection: serial.Serial,
        payload: dict[str, object],
        *,
        timeout: float,
        attempts: int = 1,
    ) -> dict[str, object]:
        raw_payload = json.dumps(payload, ensure_ascii=False) + "\n"

        for _attempt in range(attempts):
            connection.reset_input_buffer()
            connection.write(raw_payload.encode("utf-8"))
            connection.flush()

            deadline = time.time() + timeout
            while time.time() < deadline:
                line = connection.readline()
                if not line:
                    continue
                decoded = line.decode("utf-8", errors="ignore").strip()
                if not decoded:
                    continue
                try:
                    message = json.loads(decoded)
                except json.JSONDecodeError:
                    continue

                if isinstance(message, dict) and message.get("ok") is False:
                    raise ValueError(str(message.get("error", "Плата вернула ошибку provisioning.")))
                if isinstance(message, dict):
                    return message
            time.sleep(0.6)

        raise TimeoutError(
            "Плата не ответила по протоколу SmartLocker provisioning. "
            "Проверьте прошивку, COM-порт и повторите через 2-3 секунды после подключения."
        )

    @staticmethod
    def _prepare_connection(connection: serial.Serial) -> None:
        try:
            connection.dtr = False
            connection.rts = False
        except Exception:
            pass
        connection.reset_input_buffer()
        connection.reset_output_buffer()
        time.sleep(SerialProvisioningService.PREPARE_DELAY_SECONDS)
