# SmartLocker Firmware Board Matrix

This firmware set is aligned with the current hardware split:

- `ESP8266` talks to the server and handles provisioning over serial;
- `ESP32-CAM` talks to the server, handles provisioning and exposes a test camera page;
- `Arduino Nano relay A` controls one relay channel only;
- `Arduino Nano relay B` controls the second relay channel only.

## Sketches

### ESP8266

Path:

```text
firmware/esp8266/smartlocker_provisioning_test/smartlocker_provisioning_test.ino
```

Role:

- serial provisioning;
- Wi-Fi connection;
- test HTML page with logs and status.

### ESP32-CAM

Path:

```text
firmware/esp32_cam/smartlocker_camera_test/smartlocker_camera_test.ino
```

Role:

- serial provisioning;
- Wi-Fi connection;
- test HTML page with logs and camera preview;
- `/capture.jpg` for a live JPEG frame.

### Arduino Nano Relay A

Path:

```text
firmware/arduino_nano_relay_a/smartlocker_relay_a_test/smartlocker_relay_a_test.ino
```

Role:

- serial-controlled relay controller;
- provisioning with `lock_id`, `board_uid` and `relay_role`;
- relay pulse command `relay_pulse`.

Default role:

```text
relay_a
```

### Arduino Nano Relay B

Path:

```text
firmware/arduino_nano_relay_b/smartlocker_relay_b_test/smartlocker_relay_b_test.ino
```

Role:

- second serial-controlled relay controller;
- same protocol as Relay A;
- separate default role and pin mapping.

Default role:

```text
relay_b
```

## Shared protocol

All four boards understand:

- `identify`
- `provision`

Nano relay boards also understand:

- `status`
- `relay_pulse`
