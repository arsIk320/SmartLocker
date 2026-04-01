Put bundled Windows driver installers here before shipping the desktop app.

Recommended folders:

- `drivers/cp210x/CP210xVCPInstaller_x64.exe`
- `drivers/ch34x/CH341SER.EXE`
- `drivers/ftdi/CDM212364_Setup.exe`

Why multiple drivers are needed:

- ESP8266 and ESP32 themselves do not define the Windows USB driver.
- The required driver depends on the USB-UART bridge used on the actual board.
- In practice, common boards use CP210x, CH340/CH341, or FTDI.

The desktop app calls `scripts/install_bundled_drivers.ps1` to run these installers silently when they are present.
