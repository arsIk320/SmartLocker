# Render Deployment

This project can run on Render as a single public web service:

- `smartlocker-api`: FastAPI app on Render
- Telegram bot runs inside the same app through a webhook endpoint
- PostgreSQL lives on Neon

## Why this works

Render free web service is enough for the API and webhook bot.
Neon provides the shared database without requiring Render disks or a paid worker.

## Files

- Blueprint: [render.yaml](/D:/Documents/GitHub/SmartLocker/render.yaml)
- Example env vars: [.env.example](/D:/Documents/GitHub/SmartLocker/.env.example)

## Database

Use Neon and set:

```env
DATABASE_URL=postgresql+psycopg://...
```

## Telegram webhook

Set the public Render URL for both:

```env
SMARTLOCKER_API_BASE_URL=https://your-api-name.onrender.com
TELEGRAM_BOT_WEBHOOK_BASE_URL=https://your-api-name.onrender.com
```

The app will register Telegram webhook here:

```text
https://your-api-name.onrender.com/api/v1/telegram/webhook
```

## Required secrets

Set these in Render before first real use:

- `DATABASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_BOT_API_KEY`
- `TELEGRAM_BOT_WEBHOOK_BASE_URL`
- `TELEGRAM_BOT_WEBHOOK_SECRET`
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
3. Confirm the single web service from [render.yaml](/D:/Documents/GitHub/SmartLocker/render.yaml).
4. Fill in the missing secrets.
5. Create a Neon database and copy its connection string to `DATABASE_URL`.
6. After the Render service gets its public URL, set:

```env
SMARTLOCKER_API_BASE_URL=https://your-api-name.onrender.com
TELEGRAM_BOT_WEBHOOK_BASE_URL=https://your-api-name.onrender.com
```

7. Redeploy the service.
