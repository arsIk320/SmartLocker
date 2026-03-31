# Render Deployment

This project can run on Render as two services:

- `smartlocker-api`: public web service with a persistent disk and SQLite
- `smartlocker-bot`: background worker that talks to the API over Render's private network

## Why this works

The Telegram bot does not access the database directly. It only calls HTTP API endpoints.
That means SQLite can live only on the API service disk and still be used safely.

## Files

- Blueprint: [render.yaml](/D:/Documents/GitHub/SmartLocker/render.yaml)
- Example env vars: [.env.example](/D:/Documents/GitHub/SmartLocker/.env.example)

## API service

The API service uses:

```env
DATABASE_URL=sqlite:////var/data/smartlocker.db
```

The persistent disk is mounted at:

```text
/var/data
```

## Bot service

The bot can use either:

```env
TELEGRAM_BOT_API_BASE_URL=https://your-public-api.onrender.com
```

or the internal Render host/port pair:

```env
TELEGRAM_BOT_API_INTERNAL_HOST=...
TELEGRAM_BOT_API_INTERNAL_PORT=...
```

If `TELEGRAM_BOT_API_BASE_URL` is empty, the bot builds the base URL from the internal host and port.

## Required secrets

Set these in Render before first real use:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_BOT_API_KEY`
- `ADMIN_PASSWORD`
- `SMARTLOCKER_API_BASE_URL`
- `JWT_SECRET_KEY`
- `DATA_ENCRYPTION_KEY`

Optional, depending on your setup:

- TravelLine credentials
- SMTP / Brevo credentials

## Deploy flow

1. Push this repository to GitHub.
2. In Render, create a new Blueprint from the repo.
3. Confirm both services from [render.yaml](/D:/Documents/GitHub/SmartLocker/render.yaml).
4. Fill in the missing secrets.
5. After the API gets its public Render URL, set:

```env
SMARTLOCKER_API_BASE_URL=https://your-api-name.onrender.com
```

6. Redeploy the API and bot.

## Important note about SQLite

SQLite on Render needs a persistent disk, which is available only on paid plans that support disks.
The database file is tied to the API service disk and is not meant to be shared directly with another service.
