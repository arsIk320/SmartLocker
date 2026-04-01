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

Или без editable-режима:

```bash
pip install -r requirements.txt
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

## Telegram bot

Telegram-бот запускается отдельно от сайта и работает только через HTTP API.

Нужны переменные:

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_BOT_API_KEY=...
TELEGRAM_BOT_API_BASE_URL=http://127.0.0.1:8000
TELEGRAM_PROXY_URL=
```

Запуск:

```bash
python run_telegram_bot.py
```

Сценарии:

- `/access` — получить данные доступа и QR-код по коду брони и фамилии/email
- `/face` — отправить фото лица для последующей биометрической обработки

## MAX bot

MAX-бот поддерживает два режима:

- разработка: отдельный polling-процесс `python run_max_bot.py`
- production: webhook внутри того же FastAPI-сервиса

В production MAX рекомендует использовать только webhook.

Нужны переменные:

```bash
MAX_BOT_TOKEN=...
MAX_BOT_API_KEY=...
MAX_BOT_API_BASE_URL=http://127.0.0.1:8000
MAX_BOT_WEBHOOK_BASE_URL=
MAX_BOT_WEBHOOK_SECRET=
MAX_PLATFORM_API_BASE_URL=https://platform-api.max.ru
MAX_BOT_POLL_TIMEOUT=30
```

Локальный запуск через polling:

```bash
python run_max_bot.py
```

Production через тот же backend:

```bash
MAX_BOT_WEBHOOK_BASE_URL=https://your-api-name.onrender.com
MAX_BOT_WEBHOOK_SECRET=...
```

Webhook будет зарегистрирован на:

```text
https://your-api-name.onrender.com/api/v1/max/webhook
```

Сценарии:

- привязка брони по ФИО
- получение актуального QR-кода по привязанной брони
- отправка фото лица для биометрии
- отвязка брони и возврат в главное меню

## Email

Для локальной разработки можно оставить:

```bash
EMAIL_DELIVERY_MODE=console
```

Тогда коды будут печататься в консоль сервера.

## Face recognition

Базовая установка больше не тянет `dlib/face-recognition`, чтобы проект нормально ставился на Windows и Python 3.12.

Если нужен именно скрипт построения face map, ставьте отдельно:

```bash
pip install -r requirements-face.txt
```

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
