param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

& $PythonExe -m pip install pyinstaller
& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --add-data "scripts;scripts" `
    --add-data "drivers;drivers" `
    --name SmartLockerDesktop `
    desktop.py
