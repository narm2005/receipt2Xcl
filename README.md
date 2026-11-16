# receipt2Xcl backend

FastAPI service behind SlickReceipts.com. Users sign in with Google through Supabase Auth; this service checks their Supabase token, turns receipt images into structured
data (Google Cloud Vision OCR, then DeepSeek), stores each user's receipts in Postgres, and exports CSV/Excel/JSON.

## Run locally

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env   # then fill in the values
bash start.sh
```

Tests (Vision and DeepSeek are stubbed; set `TEST_DATABASE_URL` to run them on Postgres): `cd backend && pip install pytest && pytest -q`

## Configuration

All secrets come from environment variables; see `backend/.env.example`.
Required: `SUPABASE_URL`, `GOOGLE_APPLICATION_CREDENTIALS_JSON`, `DEEPSEEK_API_KEY`, and in production `DATABASE_URL`
(the Supabase Postgres "Session pooler" connection string; any Postgres such as Neon works later).
`SUPABASE_JWT_SECRET` is needed only if the Supabase project still signs tokens with the legacy shared secret.
Tables are created on start, in the `app` schema (not `public`, so Supabase's REST API does not expose them).

## API

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/auth/me` | Current user (tier, files used) |
| POST | `/receipts` | Upload 1+ images (multipart `files`), returns extracted data |
| GET | `/receipts` | The user's receipts, newest first |
| GET/DELETE | `/receipts/{id}` | One receipt |
| GET | `/receipts/export?format=csv\|xlsx\|json&ids=a,b` | Download; xlsx/json are Premium |
| GET | `/analytics` | Monthly totals by category (Premium) |

All need `Authorization: Bearer <Supabase access token>`.
`/process` and `/upload` are legacy endpoints for the old Supabase edge function; they are off unless `BACKEND_API_KEY` is set.

## Moving data from Supabase

`backend/scripts/import_from_supabase.py` copies users and processed receipts from the old Supabase tables into the app's tables once; see the docstring.
