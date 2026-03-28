# SmartLocker

Backend and desktop onboarding app for a smart lock and PMS integration platform.

## Current scope

- FastAPI application scaffold
- Desktop Windows app for lock setup
- Secure configuration via environment variables
- Initial TravelLine Read Reservation API integration for real API access
- Manual reservation sync endpoint for validating mapping logic
- Lock binding and Wi-Fi profile storage

## Quick start

1. Create a virtual environment with Python 3.11+.
2. Install dependencies:

```bash
pip install -e .
```

3. Copy `.env.example` to `.env` and fill in your TravelLine credentials and `TRAVELLINE_PROPERTY_ID`.
4. Run the API:

```bash
uvicorn app.main:app --reload
```

Or use the helper launcher:

```bash
python start.py
```

## Desktop app

Run the desktop application during development:

```bash
python desktop.py
```

The desktop flow is aimed at the installer/customer scenario:

- connect the smart lock to a computer;
- sign in to the SmartLocker account;
- create the object and door if needed;
- assign one shared `Lock ID` for the whole lock pair;
- generate and write new board UIDs for `ESP8266` and `ESP32`;
- bind the lock to the account or a specific door;
- save SSID and Wi-Fi password for the lock.

The desktop app now supports provisioning mode:

- auto-detect a connected board over `COM`;
- detect whether it is `ESP8266` or `ESP32`;
- generate a fresh shared `Lock ID`;
- generate a fresh board UID for the detected board;
- write the new UID, shared `Lock ID`, and Wi-Fi config into the board.

The serial protocol expected from the firmware is documented in [docs/provisioning_protocol.md](D:\Documents\GitHub\SmartLocker\docs\provisioning_protocol.md).

## Drivers

For ESP-based locks, Windows drivers depend on the USB-UART bridge mounted on the board, not only on the ESP chip itself.

Bundle driver installers in:

- `drivers/cp210x/CP210xVCPInstaller_x64.exe`
- `drivers/ch34x/CH341SER.EXE`
- `drivers/ftdi/CDM212364_Setup.exe`

The desktop app can launch `scripts/install_bundled_drivers.ps1` so the customer installs the required drivers together with the program.

Build a Windows `.exe`:

```powershell
./build_desktop.ps1
```

PyInstaller will create `dist/SmartLockerDesktop.exe`.

## API endpoints

- `GET /health`
- `GET /api/v1/pms/travelline/config-status`
- `POST /api/v1/pms/travelline/sync`

## Notes

- This is an initial integration layer meant to validate TravelLine Read Reservation API connectivity and normalize reservation payloads.
- Before production launch, we should add PostgreSQL models, migrations, access control, audit logging, webhook verification, token caching, and Russian personal-data compliance controls.
