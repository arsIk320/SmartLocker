# SmartLocker

FastAPI backend и Windows desktop-приложение для smart lock платформы с TravelLine.

## Как теперь работаем

- `Supabase Postgres` используется как общая БД.
- локальный сервер и desktop читают один и тот же `DATABASE_URL`.
- хостинг и Docker-обвязка из проекта убраны, чтобы не мешали текущему сценарию.

## Быстрый старт

1. Установите зависимости:

```bash
pip install -e .
```

2. Скопируйте [.env.example](D:\Documents\GitHub\SmartLocker\.env.example) в `.env`
или запустите мастер:

```bash
python start.py --setup
```

3. Укажите `DATABASE_URL` от Supabase в формате:

```bash
postgresql+psycopg://postgres.PROJECT_REF:DB_PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres?sslmode=require
```

4. Запустите сервер:

```bash
python start.py
```

5. При необходимости запустите desktop:

```bash
python desktop.py
```

Desktop при пустом `SMARTLOCKER_API_BASE_URL` работает напрямую с той же общей БД.

## Email

Для локальной разработки можно оставить:

```bash
EMAIL_DELIVERY_MODE=console
```

Тогда коды будут печататься в консоль сервера.

## Основные точки

- `GET /health`
- `GET /docs`
- web UI регистрации и кабинета
- TravelLine интеграция
- объекты, двери, привязка замка по UID
- QR-секреты и access grants

## Документация

- [docs/provisioning_protocol.md](D:\Documents\GitHub\SmartLocker\docs\provisioning_protocol.md)
- [docs/qr_lock_flow.md](D:\Documents\GitHub\SmartLocker\docs\qr_lock_flow.md)
- [docs/face-map-algorithm.md](D:\Documents\GitHub\SmartLocker\docs\face-map-algorithm.md)
- [docs/face-biometric-architecture.md](D:\Documents\GitHub\SmartLocker\docs\face-biometric-architecture.md)
- [docs/esp8266_test_firmware.md](D:\Documents\GitHub\SmartLocker\docs\esp8266_test_firmware.md)
