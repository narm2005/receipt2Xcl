# receipt2Xcl backend

FastAPI service behind SlickReceipts.com. It handles Google sign-in, turns receipt images into structured
data (Google Cloud Vision OCR, then DeepSeek), stores each user's receipts in Postgres, and exports CSV/Excel/JSON.

## Run locally

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env   # then fill in the values
bash start.sh
```

Tests (Vision, DeepSeek and Google sign-in are stubbed): `cd backend && pip install pytest && pytest -q`

## Configuration

All secrets come from environment variables; see `backend/.env.example`.
Required: `JWT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_APPLICATION_CREDENTIALS_JSON`, `DEEPSEEK_API_KEY`, and in production `DATABASE_URL` (Postgres, e.g. Neon). Tables are created on start.

## API

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/auth/google` | Exchange a Google ID token for a session token |
| GET | `/auth/me` | Current user (tier, files used) |
| POST | `/receipts` | Upload 1+ images (multipart `files`), returns extracted data |
| GET | `/receipts` | The user's receipts, newest first |
| GET/DELETE | `/receipts/{id}` | One receipt |
| GET | `/receipts/export?format=csv\|xlsx\|json&ids=a,b` | Download; xlsx/json are Premium |
| GET | `/analytics` | Monthly totals by category (Premium) |

All except `/auth/google` need `Authorization: Bearer <token>`.
`/process` and `/upload` are legacy endpoints for the old Supabase edge function; they are off unless `BACKEND_API_KEY` is set.

## Moving data from Supabase

`backend/scripts/import_from_supabase.py` copies users and processed receipts once; see the docstring.
