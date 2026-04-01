param()

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$driversRoot = Join-Path $root "drivers"

if (-not (Test-Path $driversRoot)) {
    Write-Host "Папка drivers не найдена: $driversRoot"
    exit 1
}

$packages = @(
    @{ Name = "CP210x"; Path = Join-Path $driversRoot "cp210x\CP210xVCPInstaller_x64.exe"; Args = "/quiet /norestart" },
    @{ Name = "CH34x"; Path = Join-Path $driversRoot "ch34x\CH341SER.EXE"; Args = "/S" },
    @{ Name = "FTDI"; Path = Join-Path $driversRoot "ftdi\CDM212364_Setup.exe"; Args = "/quiet" }
)

$installed = $false

foreach ($pkg in $packages) {
    if (Test-Path $pkg.Path) {
        Write-Host "Установка драйвера $($pkg.Name) из $($pkg.Path)"
        Start-Process -FilePath $pkg.Path -ArgumentList $pkg.Args -Wait
        $installed = $true
    }
}

if (-not $installed) {
    Write-Host "Не найдены файлы драйверов. Положите инсталляторы в папку drivers."
    exit 1
}

Write-Host "Установка драйверов завершена."
