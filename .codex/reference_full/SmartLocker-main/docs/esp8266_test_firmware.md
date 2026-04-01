# ESP8266 Test Firmware

File:

- `firmware/esp8266/smartlocker_provisioning_test/smartlocker_provisioning_test.ino`

## Purpose

This is a test provisioning firmware for `ESP8266` that works with the desktop SmartLocker app.

It supports:

- `identify`
- `provision`
- saving `Lock ID`
- saving a new board UID
- saving Wi-Fi SSID and password
- optional save of `owner_email` and `door_uid`
- basic HTTP status page in the connected Wi-Fi network
- event log with boot, provisioning, Wi-Fi and server start messages
- reboot after successful provisioning

## Arduino IDE setup

1. Install ESP8266 board support in Arduino IDE.
2. Install the `ArduinoJson` library.
3. Open `smartlocker_provisioning_test.ino`.
4. Select your ESP8266 board and COM port.
5. Upload the sketch.

## Protocol

The firmware implements the protocol documented in:

- `docs/provisioning_protocol.md`

## Notes

- This is a test firmware, not production firmware.
- It stores configuration in `EEPROM`.
- The desktop app writes the new board UID into the board; it is not treated as a hardware-fused ID.
- After successful Wi-Fi connection the board starts an HTTP server on port `80`.
- Open `http://<board-ip>/` in a browser to view the test page.
- JSON status is available at `http://<board-ip>/status`.
- The HTML page shows firmware version, `Lock ID`, `board UID`, current IP, timestamp and the recent log entries.
