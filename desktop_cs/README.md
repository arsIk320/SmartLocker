# SmartLocker Desktop on C#

Новая версия desktop-клиента под Windows:
- `C#`
- `.NET 8`
- `WinForms`

Папка проекта:
- `desktop_cs/SmartLockerDesktop`

Что уже перенесено:
- логин через SmartLocker API
- загрузка объектов и замков
- добавление домов и дверей
- serial identify/provision для ESP-плат
- активация замка через API + запись в плату
- тест `/health` и `/api/v1/locks/qr/current`

Архитектура:
- клиент работает через API
- одна общая серверная БД остаётся за FastAPI
- desktop не пишет напрямую в локальную БД

Как запускать после установки .NET SDK:
1. Открыть папку `desktop_cs/SmartLockerDesktop`
2. Выполнить `dotnet run`
