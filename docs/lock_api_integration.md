# SmartLocker Lock API Integration

This document is the baseline for wiring a physical lock to the SmartLocker server.

## Integration model

The lock should not access the database directly.

The correct path is:

1. desktop or web dashboard provisions the lock;
2. the server generates lock credentials;
3. the firmware stores `lock_id`, `api_key`, Wi-Fi settings, and server URL;
4. the lock communicates with the SmartLocker API over HTTP.

## Server base URL

Use the local API base URL during development:

```text
http://127.0.0.1:8000
```

For boards on the same local network, replace `127.0.0.1` with the PC's LAN IP, for example:

```text
http://192.168.1.15:8000
```

## Lock authentication

Every request from the lock must include:

```http
X-Lock-Id: LOCK-001
X-Lock-Api-Key: generated_lock_api_key
```

These values are issued during provisioning and must be stored in flash/NVS/EEPROM.

## Provisioning flow

Provisioning is initiated by desktop/client software, not by the lock itself.

### 1. Create or update lock

Endpoint:

```http
POST /api/v1/client/locks
Authorization: Bearer <owner_access_token>
Content-Type: application/json
```

Request example:

```json
{
  "lock_id": "LOCK-001",
  "device_name": "Room 12 lock",
  "wifi_ssid": "Hotel-WiFi",
  "wifi_password": "secret123",
  "port_name": "COM5",
  "door_id": "3e39a13f-8a87-4aa3-a1ff-c53cf57f98f2",
  "esp8266_uid": "ESP8266-ROOM12",
  "esp32_uid": "ESP32CAM-ROOM12"
}
```

Response example:

```json
{
  "device": {
    "id": "2d3d5f46-0ec4-4a84-a3d4-3c594b3ca36f",
    "lock_id": "LOCK-001",
    "device_name": "Room 12 lock",
    "door_id": "3e39a13f-8a87-4aa3-a1ff-c53cf57f98f2"
  },
  "provisioning": {
    "lock_id": "LOCK-001",
    "api_key": "generated_lock_api_key",
    "api_base_url": "http://127.0.0.1:8000"
  }
}
```

### 2. Flash or serial-provision the board

Write at least these values to the board:

- `api_base_url`
- `lock_id`
- `lock_api_key`
- `wifi_ssid`
- `wifi_password`

## QR flow

QR verification should stay local on the lock for speed.

### 1. Poll current QR code

Endpoint:

```http
GET /api/v1/locks/qr/current
X-Lock-Id: LOCK-001
X-Lock-Api-Key: generated_lock_api_key
```

Response example:

```json
{
  "code": "48290117534",
  "door_uid": "A1B2C3D4E5",
  "issued_at": "2026-03-30T18:00:00+00:00",
  "expires_at": "2026-03-30T19:00:00+00:00",
  "ttl_seconds": 3472,
  "valid_for_seconds": 3600
}
```

### 2. Firmware logic

Recommended firmware algorithm:

1. after boot, fetch current QR code;
2. refresh it every 30-60 seconds;
3. store `code` and `expires_at` locally;
4. when the scanner reads a QR payload, compare it with the locally stored `code`;
5. if it matches, open the relay immediately without waiting for another network request.

### 3. Relay action

On a positive QR match the lock should open the relay directly.

Recommended action:

1. set relay pin `HIGH`;
2. keep it active for the configured unlock interval;
3. set relay pin `LOW`.

## Face verification flow

The final hardware flow should be:

1. guest uploads face photos through Telegram;
2. the server builds one or more face maps for the guest booking;
3. `ESP32-CAM` captures a live frame;
4. the lock sends the frame to the server;
5. the server compares the live frame to the stored face map;
6. if matched, the lock opens the relay.

### Planned endpoint

The current codebase already reserves this route:

```http
POST /api/v1/locks/face/verify
X-Lock-Id: LOCK-001
X-Lock-Api-Key: generated_lock_api_key
Content-Type: multipart/form-data
```

Planned request format:

- form field `image`: current JPEG frame from `ESP32-CAM`
- optional field `reservation_code`: use only if the firmware knows the booking context

Planned success response:

```json
{
  "open_door": true,
  "reason": "face_match",
  "reservation_external_id": "20260328-64946-423932384",
  "distance": 0.48,
  "confidence": 0.73
}
```

Planned deny response:

```json
{
  "open_door": false,
  "reason": "face_mismatch",
  "reservation_external_id": "20260328-64946-423932384",
  "distance": 0.91,
  "confidence": 0.39
}
```

## Recommended firmware state machine

### Boot

1. load saved configuration;
2. connect to Wi-Fi;
3. verify API reachability;
4. fetch current QR code.

### Idle

1. keep Wi-Fi alive;
2. refresh QR code periodically;
3. wait for:
   - QR scan event;
   - face scan request;
   - admin maintenance mode.

### QR event

1. read scanned QR text;
2. compare with locally cached `code`;
3. if equal, open relay;
4. optionally log event locally and later send telemetry.

### Face event

1. capture frame from camera;
2. send frame to `/api/v1/locks/face/verify`;
3. if `open_door=true`, open relay;
4. if denied, show status LED/buzzer pattern.

## Telemetry to add next

These endpoints are still worth adding tomorrow:

- `POST /api/v1/locks/events`
  - QR success
  - QR failure
  - face success
  - face failure
  - tamper
  - heartbeat
- `POST /api/v1/locks/heartbeat`
  - online status
  - firmware version
  - Wi-Fi signal
  - power status

Suggested event payload:

```json
{
  "event_type": "qr_success",
  "occurred_at": "2026-03-30T18:14:21+00:00",
  "firmware_version": "0.3.0",
  "rssi": -61,
  "details": {
    "door_uid": "A1B2C3D4E5"
  }
}
```

## Development checklist for tomorrow

## Local lock test flow

Use this sequence for the first end-to-end tests with a real board:

1. start the API server:

```powershell
python start.py
```

2. start the desktop app:

```powershell
python desktop.py
```

3. in Desktop:
   - create a house and a door;
   - open `Подключение замка`;
   - detect the board;
   - select Wi-Fi and the target door;
   - activate the lock.

4. after activation, copy or verify the generated values:
   - `lock_id`
   - `api_key`
   - `api_base_url`

5. open the `Тест lock API` tab in Desktop:
   - click `Подставить последний lock`;
   - click `Проверить /health`;
   - click `Получить QR`.

6. write the same values into firmware or test requests:
   - `lock_id`
   - `api_key`
   - `api_base_url`

7. emulate the board request:

```http
GET /api/v1/locks/qr/current
X-Lock-Id: <lock_id>
X-Lock-Api-Key: <api_key>
```

If this responds with a QR payload, the software side of lock provisioning is ready for hardware tests.

1. implement `POST /api/v1/locks/face/verify`;
2. add lock heartbeat endpoint;
3. add lock event logging endpoint;
4. wire the firmware to `GET /api/v1/locks/qr/current`;
5. wire `ESP32-CAM` frame upload to `POST /api/v1/locks/face/verify`;
6. add a small retry/backoff policy for unstable Wi-Fi.
