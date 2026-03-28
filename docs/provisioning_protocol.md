# SmartLocker Provisioning Protocol

The desktop application provisions ESP boards over a serial port using newline-delimited JSON.

Default serial settings:

- Baud rate: `115200`
- Encoding: `UTF-8`
- Framing: one JSON object per line

## Identify request

Desktop sends:

```json
{"action":"identify","protocol":"smartlocker-provisioning-v1"}
```

Board should respond:

```json
{"ok":true,"protocol":"smartlocker-provisioning-v1","chip":"ESP8266","firmware_version":"0.1.0","board_uid":"TEMP-BOOT"}
```
or
```json
{"ok":true,"protocol":"smartlocker-provisioning-v1","chip":"ESP32","firmware_version":"0.1.0","board_uid":"TEMP-BOOT"}
```

## Provision request

Desktop sends:

```json
{
  "action":"provision",
  "protocol":"smartlocker-provisioning-v1",
  "payload":{
    "chip":"ESP8266",
    "lock_id":"LOCK-12AB34CD",
    "board_uid":"ESP8266-12AB34CD",
    "device_name":"Room 12 lock",
    "wifi_ssid":"Hotel-WiFi",
    "wifi_password":"secret123",
    "owner_email":"owner@example.com",
    "door_uid":"A1B2C3D4E5"
  }
}
```

Board should:

- validate the payload;
- store configuration in flash/NVS/EEPROM;
- set the new board UID from `payload.board_uid`;
- set the shared lock ID from `payload.lock_id`;
- save Wi-Fi credentials;
- restart or reconnect if needed.

Successful response:

```json
{"ok":true,"status":"provisioned","restart_required":true,"wifi_connected":true,"ip_address":"192.168.1.77"}
```

Error response:

```json
{"ok":false,"error":"wifi_ssid is required"}
```
