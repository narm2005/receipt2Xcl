import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.auth.transport import requests as google_requests
from google.cloud import vision
from google.oauth2 import id_token
from pydantic import BaseModel
from sqlalchemy.orm import Session

import convert
from database import CachedResult, get_db

load_dotenv()


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} must be set")
    return value


# --- Secrets and settings (all from the environment, never from source) ---
# Shared secret the Supabase edge function sends in the X-API-Key header.
BACKEND_API_KEY = _required_env("BACKEND_API_KEY")
# Secret used to sign the session tokens issued by /auth/callback.
JWT_SECRET = _required_env("JWT_SECRET")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "https://slickreceipts.com,https://www.slickreceipts.com"
    ).split(",")
    if origin.strip()
]
MAX_FILES_PER_REQUEST = int(os.getenv("MAX_FILES_PER_REQUEST", "10"))
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_MB", "10")) * 1024 * 1024

# Google Vision credentials come in as JSON in an env var; the client library wants a file path.
credentials_info = json.loads(_required_env("GOOGLE_APPLICATION_CREDENTIALS_JSON"))
with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as temp:
    json.dump(credentials_info, temp)
    temp.flush()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp.name

UPLOAD_FOLDER = "output"
JSON_FOLDER = os.path.join(UPLOAD_FOLDER, "json")
os.makedirs(JSON_FOLDER, exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


def require_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    """Only callers that hold BACKEND_API_KEY (the Supabase edge function) may spend OCR/LLM credits."""
    if not x_api_key or not hmac.compare_digest(x_api_key, BACKEND_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")


class SupabaseFilePayload(BaseModel):
    file_id: str
    file_name: str
    user_id: str
    content_base64: str


class SupabaseBulkRequest(BaseModel):
    files: List[SupabaseFilePayload]


class GoogleAuthRequest(BaseModel):
    credential: str


def sanitize_json_string(raw: str) -> str:
    raw = raw.strip().strip("```json").strip("```")
    raw = raw.replace("'", '"')
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    raw = re.sub(r'(?<={|,)\s*(\w+)\s*:', r'"\1":', raw)
    return raw


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Do not echo the request body back: it can contain whole receipt images.
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


def compute_sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def extract_google_text(content: bytes) -> str:
    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=content)
    response = client.text_detection(image=image)
    return response.text_annotations[0].description if response.text_annotations else ""


async def parse_with_deepseek(text: str) -> dict:
    receipt_parser = convert.make_receiptParser()
    fewshot_prompt = convert.make_fewshot_prompt(receipt_parser.get_format_instructions())
    model = convert.make_deepseek()
    chain = convert.make_chain(fewshot_prompt, model, receipt_parser)
    response = chain.invoke({"input": text})
    raw = json.dumps({"ReceiptInfo": json.loads(response.model_dump_json())})
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(sanitize_json_string(raw))


async def extract_receipt(contents: bytes, db: Session) -> dict:
    """OCR + structure one receipt, using the cache so the same image is never paid for twice."""
    file_hash = compute_sha256(contents)
    cached = db.query(CachedResult).filter(CachedResult.file_hash == file_hash).first()
    if cached:
        return json.loads(cached.json_data)

    extracted_text = extract_google_text(contents)
    parsed = await parse_with_deepseek(extracted_text)
    db.add(CachedResult(file_hash=file_hash, json_data=json.dumps(parsed)))
    db.commit()
    return parsed


def summarize(parsed: dict) -> dict:
    receipt = parsed.get("ReceiptInfo", {})
    items = receipt.get("ITEMS", [])
    return {
        "merchant": receipt.get("merchant", ""),
        "date": receipt.get("receiptDate", ""),
        "total": receipt.get("total", 0.0),
        "items": [
            {
                "description": item.get("description", ""),
                "amount": item.get("totalPrice", 0.0),
                "category": item.get("category", ""),
            }
            for item in items
        ],
    }


def check_file_count(count: int) -> None:
    if count == 0:
        raise HTTPException(status_code=400, detail="No files provided.")
    if count > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=413, detail=f"At most {MAX_FILES_PER_REQUEST} files per request."
        )


def check_file_size(contents: bytes) -> None:
    if len(contents) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File is too large.")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload", dependencies=[Depends(require_api_key)])
async def upload_receipts(
    files: List[UploadFile] = File(...),
    lang: Optional[str] = Form(None),
    auto_detect: Optional[bool] = Form(False),
    db: Session = Depends(get_db),
):
    check_file_count(len(files))
    receipts = []
    for file in files:
        contents = await file.read()
        check_file_size(contents)
        try:
            receipts.append({"file_name": file.filename, **summarize(await extract_receipt(contents, db))})
        except Exception as e:
            print(f"Error processing an uploaded file: {type(e).__name__}: {str(e)[:300]}")
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
            print(f"Error processing file {file.file_id}: {type(e).__name__}: {str(e)[:300]}")
            results.append({"file_id": file.file_id, "file_name": file.file_name, "error": "Failed to process file"})

    # "files" is what the edge function reads; "receipts" is kept for older callers.
    return {"files": results, "receipts": results}


@app.post("/auth/callback")
async def google_auth(data: GoogleAuthRequest):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    try:
        idinfo = id_token.verify_oauth2_token(data.credential, google_requests.Request(), GOOGLE_CLIENT_ID)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google credential")

    payload = {
        "sub": idinfo.get("sub"),
        "email": idinfo.get("email"),
        "name": idinfo.get("name"),
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return {
        "success": True,
        "token": token,
        "name": idinfo.get("name"),
        "email": idinfo.get("email"),
        "picture": idinfo.get("picture"),
    }
