# Borsa Research Engine

## Required Environment

Copy `.env.example` to `.env` and set at least:

- `DATABASE_URL`
- `SYNC_DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET`

Optional, but used by parts of the app:

- `API_KEY`
- `NEXT_PUBLIC_API_URL`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`
- `SLACK_WEBHOOK_URL`

## Local Setup

1. Create and activate the Python virtual environment.
2. Install backend dependencies.
3. Run `python setup_db.py` if you need to provision a local Postgres database.
4. Run Alembic migrations with `alembic upgrade head`.

## Run Backend

From `backend/`:

```powershell
uvicorn app.main:app --reload --port 8000
```

## Run Frontend

From `frontend/`:

```powershell
npm install
npm run dev
```

## Test

```powershell
npm run build
.venv\Scripts\python.exe -m pytest -q
```

## Notes

- `JWT_SECRET` is required for login and token verification.
- Notification preferences are stored in the database and shared across devices.
- `data-status` reads the backend summary endpoint instead of using a stale snapshot.
