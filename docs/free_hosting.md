# Free Test Hosting

This project can be deployed in a free test setup without renting a VPS first.

## Recommended stack

- App/API hosting: `Koyeb`
- Free public domain: `your-app.koyeb.app`
- Hosted PostgreSQL: `Supabase`

## Why this stack

### Koyeb for the app

Koyeb documents:

- one free web service on the Free plan;
- a free app domain on `*.koyeb.app`;
- scale-to-zero on free services after inactivity.

This is enough for a test launch of the site and API.

### Supabase for PostgreSQL

Supabase documents a Free plan with:

- up to 2 active projects;
- managed Postgres included;
- 500 MB database size.

For SmartLocker this is a better free database option than trying to keep the database inside the same free app platform.

## Why not keep the database on free app hosting

Koyeb also offers databases, but its documentation says the Free plan includes only a very small amount of monthly database active time.

For SmartLocker, where the site, TravelLine sync, and future lock traffic should all use the same database, an external managed Postgres is the safer free test choice.

This is an engineering recommendation based on the official platform limits above.

## Deployment flow

1. Create a Supabase project.
2. Copy the Postgres connection string.
3. Create a Koyeb app from this GitHub repository.
4. Configure environment variables from `.env.koyeb.example`.
5. Set `DATABASE_URL` to the hosted Supabase Postgres URL.
6. Deploy the app from the repository root using the included `Dockerfile`.

## Required environment variables

Minimum production variables:

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `DATA_ENCRYPTION_KEY`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
- `SESSION_COOKIE_SECURE=true`

If email verification is required in the deployed test instance:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `SMTP_USE_TLS`

If TravelLine sync is needed globally:

- `TRAVELLINE_AUTH_URL`
- `TRAVELLINE_API_BASE_URL`
- `TRAVELLINE_TIMEOUT_SECONDS`

## Notes for this repository

- The application already supports PostgreSQL through `DATABASE_URL`.
- The repository now includes `psycopg[binary]` for hosted Postgres connections.
- Cookies can be marked secure in production with `SESSION_COOKIE_SECURE=true`.

## Suggested first test URL

Use a Koyeb app name like:

- `smartlocker-test`

Then the public address will be:

- `https://smartlocker-test.koyeb.app`

## Official sources

- [Koyeb Pricing](https://www.koyeb.com/pricing)
- [Koyeb App Domains](https://www.koyeb.com/docs/reference/apps)
- [Supabase Pricing](https://supabase.com/pricing)
