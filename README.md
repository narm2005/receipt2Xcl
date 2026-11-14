# receipt2Xcl backend

FastAPI service that turns a receipt image into structured data (Google Cloud Vision OCR, then DeepSeek).
It is called by the SlickReceipts Supabase edge function `process-receipt`.

## Run locally

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env   # then fill in the values
bash start.sh
```

## Configuration

All secrets come from environment variables; see `backend/.env.example`.
The service refuses to start without `BACKEND_API_KEY`, `JWT_SECRET` and `GOOGLE_APPLICATION_CREDENTIALS_JSON`.

`/process` and `/upload` require the header `X-API-Key: <BACKEND_API_KEY>`.
The same value must be set as `BACKEND_API_KEY` in the Supabase edge function secrets.
