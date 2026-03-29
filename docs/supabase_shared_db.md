# Supabase Shared DB

Этот режим нужен, когда:

- сервер запускается локально;
- desktop запускается локально;
- данные должны быть общими;
- вся синхронизация идёт через одну базу в Supabase.

## Формат DATABASE_URL

Используйте строку вида:

```text
postgresql+psycopg://postgres.PROJECT_REF:DB_PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres?sslmode=require
```

Важно:

- использовать именно `postgresql+psycopg://`
- использовать pooler-хост Supabase
- не использовать локальные хосты вроде `db` или `localhost`, если хотите общую облачную БД

## Как настроить

1. Создайте `.env` или `.local.env`.
2. Запишите туда `DATABASE_URL`.
3. Запустите сервер:

```powershell
python start.py
```

4. Запустите desktop:

```powershell
python desktop.py
```

## Как работает desktop

Если `SMARTLOCKER_API_BASE_URL` пустой, desktop работает напрямую с общей БД.

Если `SMARTLOCKER_API_BASE_URL` указан, desktop использует HTTP API сайта.
