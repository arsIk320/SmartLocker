# QR Lock Flow

## What is stored on the server

Each door now has:

- its own encrypted QR secret;
- secret rotation timestamp;
- bound lock UID.

Each saved lock device now has:

- `lock_id`;
- per-device API key;
- optional door binding.

## How the QR code is generated

The server does not store one static QR code forever.

Instead:

1. The door has a secret.
2. The current time window is calculated in 30-second intervals.
3. The server derives an 11-digit numeric code using:
   - door UID;
   - current time window;
   - door secret.
4. The lock requests the current code from the API.
5. The QR scanner reads the scanned QR payload.
6. The Arduino compares:
   - scanned code;
   - current server-derived code.

If they match, the relay opens.

## Why this is faster and safer

- the lock compares locally, so the scanner path does not wait for a cloud round-trip for every scan;
- the code changes every 30 seconds;
- the door secret is encrypted in the database;
- the lock authenticates with its own API key.

## Endpoints

### For desktop / client software

- `POST /api/v1/client/locks`
- `GET /api/v1/client/objects`
- `POST /api/v1/client/doors/{door_id}/bind-lock`
- `GET /api/v1/client/doors/{door_id}/qr/current`
- `POST /api/v1/client/doors/{door_id}/qr/rotate`

### For the lock

- `GET /api/v1/locks/qr/current`
  - headers:
    - `X-Lock-Id`
    - `X-Lock-Api-Key`

- `POST /api/v1/locks/face/verify`
  - currently returns a structured deny response until face verification is fully implemented

## Firmware values to fill manually for now

In the ESP sketches set:

- `lock_id`
- `lock_api_key`
- Wi-Fi SSID/password
- server URL

## Relay path

The QR controller already opens the relay directly via:

- `LOCK_PIN 3`

So for the QR path there is no need to send the open command through another Arduino after successful QR comparison.
