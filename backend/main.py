
import cv2
import numpy as np
import torch
from PIL import Image
import httpx
import pandas as pd
import uuid
import os
import json
import re
from dotenv import load_dotenv
import convert
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from typing import List, Optional
from google.cloud import vision
from sqlalchemy.orm import Session
from database import get_db, CachedResult, UploadLog
import hashlib
from datetime import date
from pydantic import BaseModel
from google.oauth2 import id_token
from google.auth.transport import requests
import jwt
from datetime import datetime, timedelta
import base64
import tempfile



from fastapi.responses import StreamingResponse, FileResponse
SECRET_KEY = "a-string-secret-at-least-256-bits-long"  # Use a strong secret in production


load_dotenv()
#GOOGLE_APPLICATION_CREDENTIALS="google_cloud_credentials.json"
# Read JSON from environment
credentials_info = json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
# creds_json_str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
# credentials_info = json.loads(creds_json_str)
# Write to a temporary file (if required by library)
with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp:
    json.dump(credentials_info, temp)
    temp.flush()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp.name

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')  # Replace with your client ID

DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
HEADERS = {
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    "Content-Type": "application/json"
}


app = FastAPI()

client = vision.ImageAnnotatorClient()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SupabaseProcessRequest(BaseModel):
    file_id: str
    file_name: str
    user_id: str
    file_base64: str

# Constants
#EXCEL_PATH = "structured_receipt.xlsx"
# Configuration
UPLOAD_FOLDER = "output"
JSON_FOLDER = os.path.join(UPLOAD_FOLDER, "json")
EXCEL_PATH = os.path.join(UPLOAD_FOLDER, "consolidated_receipts.xlsx")

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(JSON_FOLDER, exist_ok=True)




class GoogleAuthRequest(BaseModel):
    credential: str


def sanitize_json(raw: str) -> dict:
    """Robust JSON sanitizer"""
    raw = raw.strip().strip("```json").strip("```")
    raw = re.sub(r"(?<!\\)'", '"', raw)  # Replace single quotes
    raw = re.sub(r",\s*([}\]])", r"\1", raw)  # Remove trailing commas
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: Extract JSON substring
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(match.group()) if match else {"error": "Invalid JSON"}

def sanitize_json_string(raw: str) -> str:
    # Remove Markdown code block if any
    raw = raw.strip().strip("```json").strip("```")

    # Replace single quotes with double quotes (very common issue)
    raw = raw.replace("'", '"')

    # Remove trailing commas before object/array close
    raw = re.sub(r",\s*([}\]])", r"\1", raw)

    # Add quotes around unquoted keys (e.g., Vendor: -> "Vendor":)
    raw = re.sub(r'(?<={|,)\s*(\w+)\s*:', r'"\1":', raw)

    return raw

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"detail": exc.errors(), "body": exc.body},
    )



@app.post("/upload")
async def upload_receipts(
    request: Request,
    files: List[UploadFile] = File(...),
    lang: Optional[str] = Form(None),
    auto_detect: Optional[bool] = Form(False),
    db: Session = Depends(get_db)
):
    ip_address = request.client.host
    today = date.today()
    # # ✅ Rate limit check
    # if db.query(UploadLog).filter(UploadLog.ip == ip_address, UploadLog.upload_date == today).count() >= 3:
    #     raise HTTPException(status_code=403, detail="Free daily upload limit (3) reached.")

    all_rows = []
    all_receipts = []

    for file in files:
        try:
            contents = await file.read()
            file_hash = compute_sha256(contents)

            # Check cache
            cached = db.query(CachedResult).filter(CachedResult.file_hash == file_hash).first()
            if cached:
                parsed = json.loads(cached.json_data)
                source = "cache"
            else:
                temp_path = os.path.join(UPLOAD_FOLDER, f"temp_{uuid.uuid4().hex}.png")
                with open(temp_path, "wb") as f:
                    f.write(contents)

                extracted_text = extract_google_text(contents)
                json_path = os.path.join(JSON_FOLDER, f"{uuid.uuid4().hex}.json")
                await parse_with_deepseek(extracted_text, json_path)

                with open(json_path) as f:
                    raw = f.read()
                try:
                    parsed = json.loads(raw)
                except:
                    parsed = json.loads(sanitize_json_string(raw))

                db.add(CachedResult(file_hash=file_hash, json_data=json.dumps(parsed)))
                db.commit()
                os.remove(temp_path)
                source = "deepseek"

            db.add(UploadLog(ip=ip_address, upload_date=today))
            db.commit()

            receipt = parsed.get("ReceiptInfo", {})
            items = receipt.get("ITEMS", [])

            # For Excel export
            for item in items:
                all_rows.append({
                    "ReceiptFile": file.filename,
                    "Merchant": receipt.get("merchant", ""),
                    "Address": receipt.get("address", ""),
                    "City": receipt.get("city", ""),
                    "State": receipt.get("state", ""),
                    "PhoneNumber": receipt.get("phoneNumber", ""),
                    "ReceiptDate": receipt.get("receiptDate", ""),
                    "ReceiptTime": receipt.get("receiptTime", ""),
                    "TotalItems": receipt.get("totalItems", ""),
                    "DiningOptions": receipt.get("diningOptions", ""),
                    "PaymentType": receipt.get("paymentType", ""),
                    "CreditCardType": receipt.get("creditCardType", ""),
                    "TotalDiscount": receipt.get("totalDiscount", 0.0),
                    "Tax": receipt.get("tax", 0.0),
                    "Total": receipt.get("total", 0.0),
                    "Description": item.get("description", ""),
                    "UnabbreviatedDescription": item.get("unabbreviatedDescription", ""),
                    "IncludedItems": ", ".join(item.get("includedItems", [])),
                    "Quantity": item.get("quantity", 0),
                    "UnitPrice": item.get("unitPrice", 0.0),
                    "TotalPrice": item.get("totalPrice", 0.0),
                    "DiscountAmount": item.get("discountAmount", 0.0)
                })

            # For frontend preview (all receipts)
            all_receipts.append({
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
            })

        except Exception as e:
            print(f"Error processing file {file.filename}: {str(e)}")
            continue

    # Save to Excel
    if all_rows:
        df = pd.DataFrame(all_rows)
        if os.path.exists(EXCEL_PATH):
            with pd.ExcelWriter(EXCEL_PATH, mode='a', engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name=f"Receipts_{pd.Timestamp.now():%Y%m%d_%H%M%S}", index=False)
        else:
            df.to_excel(EXCEL_PATH, index=False)

        # Save all_receipts to a JSON file for export endpoints
        with open(os.path.join(UPLOAD_FOLDER, "latest_receipts.json"), "w") as f:
            json.dump(all_receipts, f, indent=2)

        return {
            "message": "Success",
            "processed_files": len(files),
            "total_items": len(all_rows),
            "receipts": all_receipts,  # <-- Return all receipts as a list
            "excel_url": "/download"
        }

    raise HTTPException(status_code=400, detail="No valid receipt data could be extracted.")


def extract_google_text(content: bytes) -> str:
    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=content)

    # Only request TEXT_DETECTION to reduce costs
    response = client.text_detection(image=image)
    return response.text_annotations[0].description if response.text_annotations else ""

async def parse_with_deepseek(text: str, json_path: str) -> dict:

    receiptParser = convert.make_receiptParser()
    fewshot_prompt = convert.make_fewshot_prompt(receiptParser.get_format_instructions())
    # model = convert.make_model(model="gpt-4-1106-preview", temperature=1.00, openai_api_key=openai_api_key)
    model = convert.make_deepseek()
    chain = convert.make_chain(fewshot_prompt, model, receiptParser)
    response = chain.invoke({"input": text})
    # with 'a' in open() it will create or append to current file
    with open(json_path, 'a') as fp:  # Write each JSON object as it gets parsed
        # write each receipt JSON on a new line
        fp.write(json.dumps({"ReceiptInfo": json.loads(response.model_dump_json())}) + "\n")



@app.get("/download")
def download_excel():
    if not os.path.exists(EXCEL_PATH):
        raise HTTPException(status_code=404, detail="Excel file not found")

    from fastapi.responses import FileResponse
    return FileResponse(EXCEL_PATH, filename="consolidated_receipts.xlsx")

def compute_sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()



@app.get("/export/json")
def export_json():
    json_path = os.path.join(UPLOAD_FOLDER, "latest_receipts.json")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="No processed receipts found.")
    return FileResponse(json_path, filename="receipts.json", media_type="application/json")

@app.get("/export/csv")
def export_csv():
    json_path = os.path.join(UPLOAD_FOLDER, "latest_receipts.json")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="No processed receipts found.")

    with open(json_path) as f:
        receipts = json.load(f)

    # Flatten for CSV
    rows = []
    for receipt in receipts:
        for item in receipt.get("items", []):
            rows.append({
                "Merchant": receipt.get("merchant", ""),
                "Date": receipt.get("date", ""),
                "Total": receipt.get("total", 0.0),
                "Description": item.get("description", ""),
                "Amount": item.get("amount", 0.0),
                "Category": item.get("category", ""),
            })

    df = pd.DataFrame(rows)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=receipts.csv"}
    )

@app.post("/auth/callback")
async def google_auth(data: GoogleAuthRequest):
    try:
        idinfo = id_token.verify_oauth2_token(
            data.credential,
            requests.Request(),
            GOOGLE_CLIENT_ID
        )
        # Create JWT payload
        payload = {
            "email": idinfo.get("email"),
            "name": idinfo.get("name"),
            "exp": datetime.utcnow() + timedelta(hours=12)
        }
        token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
        return {
            "success": True,
            "token": token,
            "name": idinfo.get("name"),
            "email": idinfo.get("email"),
            "picture": idinfo.get("picture"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


#@router.post("/process")
@app.post("/process")
async def process_from_supabase(request_data: SupabaseProcessRequest, db: Session = Depends(get_db)):
    try:
        contents = base64.b64decode(request_data.file_base64)
        file_hash = compute_sha256(contents)

        print("Coming Here")
        # Cache check
        cached = db.query(CachedResult).filter(CachedResult.file_hash == file_hash).first()
        if cached:
            parsed = json.loads(cached.json_data)
        else:
            temp_path = os.path.join(UPLOAD_FOLDER, f"temp_{uuid.uuid4().hex}.png")
            with open(temp_path, "wb") as f:
                f.write(contents)

            extracted_text = extract_google_text(contents)
            print(extracted_text)
            json_path = os.path.join(JSON_FOLDER, f"{uuid.uuid4().hex}.json")
            await parse_with_deepseek(extracted_text, json_path)

            with open(json_path) as f:
                raw = f.read()

            try:
                parsed = json.loads(raw)
            except:
                parsed = json.loads(sanitize_json_string(raw))

            db.add(CachedResult(file_hash=file_hash, json_data=json.dumps(parsed)))
            db.commit()
            os.remove(temp_path)

        receipt = parsed.get("ReceiptInfo", {})
        items = receipt.get("ITEMS", [])

        # Return format compatible with Supabase Edge Function
        return {
            "merchant": receipt.get("merchant", ""),
            "total": receipt.get("total", 0.0),
            "items": [
                {
                    "description": item.get("description", ""),
                    "amount": item.get("totalPrice", 0.0),
                    "category": item.get("category", ""),
                }
                for item in items
            ]
        }

    except Exception as e:
        print(f"Error processing base64 file: {str(e)}")
        raise HTTPException(status_code=400, detail="Failed to process receipt.")


