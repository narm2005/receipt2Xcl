import base64
import binascii
import hmac
import os
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from database import get_db  # noqa: E402
from processing import extract_receipt, summarize  # noqa: E402
from routes import router  # noqa: E402
from ca import router as ca_router  # noqa: E402

# Shared secret for the old Supabase edge function (legacy /process and /upload).
# Leave unset once the app no longer uses Supabase: those endpoints are then switched off.
BACKEND_API_KEY = os.getenv("BACKEND_API_KEY", "")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "https://slickreceipts.com,https://www.slickreceipts.com"
    ).split(",")
    if origin.strip()
]
MAX_FILES_PER_REQUEST = int(os.getenv("MAX_FILES_PER_REQUEST", "10"))
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_MB", "10")) * 1024 * 1024

app = FastAPI(title="SlickReceipts API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    expose_headers=["Content-Disposition"],
)

app.include_router(router)
app.include_router(ca_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Do not echo the request body back: it can contain whole receipt images.
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------- Legacy endpoints for the Supabase edge function (remove after cutover) ----------


def require_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    if not BACKEND_API_KEY:
        raise HTTPException(status_code=503, detail="Legacy endpoint disabled")
    if not x_api_key or not hmac.compare_digest(x_api_key, BACKEND_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")


class SupabaseFilePayload(BaseModel):
    file_id: str
    file_name: str
    user_id: str
    content_base64: str


class SupabaseBulkRequest(BaseModel):
    files: List[SupabaseFilePayload]


def check_file_count(count: int) -> None:
    if count == 0:
        raise HTTPException(status_code=400, detail="No files provided.")
    if count > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=413, detail=f"At most {MAX_FILES_PER_REQUEST} files per request.")


def check_file_size(contents: bytes) -> None:
    if len(contents) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File is too large.")


@app.post("/upload", dependencies=[Depends(require_api_key)])
async def upload_receipts_legacy(files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    check_file_count(len(files))
    receipts = []
    for file in files:
        contents = await file.read()
        check_file_size(contents)
        try:
            receipts.append({"file_name": file.filename, **summarize(await extract_receipt(contents, db))})
        except Exception as e:
            print(f"Error processing an uploaded file: {type(e).__name__}: {str(e)[:300]}", flush=True)
            receipts.append({"file_name": file.filename, "error": "Failed to process file"})

    if not any("error" not in r for r in receipts):
        raise HTTPException(status_code=400, detail="No valid receipt data could be extracted.")
    return {"message": "Success", "processed_files": len(files), "receipts": receipts}


@app.post("/process", dependencies=[Depends(require_api_key)])
async def process_from_supabase(request_data: SupabaseBulkRequest, db: Session = Depends(get_db)):
    check_file_count(len(request_data.files))
    results = []

    for file in request_data.files:
        try:
            contents = base64.b64decode(file.content_base64, validate=True)
        except (binascii.Error, ValueError):
            results.append({"file_id": file.file_id, "file_name": file.file_name, "error": "Invalid file data"})
            continue
        check_file_size(contents)

        try:
            summary = summarize(await extract_receipt(contents, db))
            results.append({"file_id": file.file_id, "file_name": file.file_name, **summary})
        except Exception as e:
            print(f"Error processing file {file.file_id}: {type(e).__name__}: {str(e)[:300]}", flush=True)
            results.append({"file_id": file.file_id, "file_name": file.file_name, "error": "Failed to process file"})

    # "files" is what the edge function reads; "receipts" is kept for older callers.
    return {"files": results, "receipts": results}
