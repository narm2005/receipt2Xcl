
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
from typing import List, Optional
from google.cloud import vision
from sqlalchemy.orm import Session
from database import get_db, CachedResult, UploadLog
import hashlib
from datetime import date

load_dotenv()

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


# Constants
#EXCEL_PATH = "structured_receipt.xlsx"
# Configuration
UPLOAD_FOLDER = "output"
JSON_FOLDER = os.path.join(UPLOAD_FOLDER, "json")
EXCEL_PATH = os.path.join(UPLOAD_FOLDER, "consolidated_receipts.xlsx")

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(JSON_FOLDER, exist_ok=True)




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




# @app.post("/upload")
# async def upload_receipts(
#         files: List[UploadFile] = File(...),
#         lang: Optional[str] = Form(None),
#         auto_detect: Optional[bool] = Form(False)
# ):
#     print(f"Received files: {[file.filename for file in files]}")
#     print(f"Lang: {lang}, Auto-detect: {auto_detect}")
#
#     all_rows = []  # This will store data from all receipts
#
#     for file in files:
#         try:
#             contents = await file.read()
#             random_json_filename = f"{uuid.uuid4().hex}.json"
#             json_path = os.path.join(JSON_FOLDER, random_json_filename)
#             random_temp_path = f"temp_{uuid.uuid4().hex}.png"
#             temp_path = os.path.join(UPLOAD_FOLDER, random_temp_path)
#
#             with open(temp_path, "wb") as f:
#                 f.write(contents)
#
#             # # Process the image with Google Vision API
#             # image = vision.Image(content=contents)
#             # response = client.text_detection(image=image)
#             # extracted_text = response.text_annotations[0].description
#
#             # # 1. Check cache first
#             # if cached := await get_cached_result(contents):
#             #     return {"status": "success", "source": "cache", "data": cached}
#
#             # 2.
#
#             try:
#                 extracted_text = extract_google_text(contents)
#                 print(extracted_text)
#
#                 # Convert OCR to JSON (assuming parse_with_deepseek exists)
#                 await parse_with_deepseek(extracted_text, json_path)
#                 # 3. Cache results (skip for files >5MB to avoid high costs)
#                 # if len(contents) < 5_000_000:
#                 #     await cache_result(contents, parsed_data)
#                 # return {"status": "success", "source": "vision_api", "data": parsed_data}
#
#             except Exception as e:
#                  raise HTTPException(500, f"OCR processing failed: {str(e)}")
#
#             try:
#                 with open(json_path) as f:
#                     data = f.read()
#                     parsed = json.loads(data)
#             except json.JSONDecodeError:
#                 print("❗ Raw DeepSeek response not valid JSON. Attempting to sanitize...")
#                 try:
#                     cleaned_json = sanitize_json_string(data)
#                     parsed = json.loads(cleaned_json)
#                 except Exception as e:
#                     raise HTTPException(
#                         status_code=500,
#                         detail=f"Failed to parse JSON even after sanitizing. Error: {str(e)}. Raw: {data}"
#                     )
#
#             # Extract data from the receipt
#             receipt = parsed.get("ReceiptInfo", {})
#             items = receipt.get("ITEMS", [])
#
#             for item in items:
#                 all_rows.append({
#                     "ReceiptFile": file.filename,
#                     "Merchant": receipt.get("merchant", ""),
#                     "Address": receipt.get("address", ""),
#                     "City": receipt.get("city", ""),
#                     "State": receipt.get("state", ""),
#                     "PhoneNumber": receipt.get("phoneNumber", ""),
#                     "ReceiptDate": receipt.get("receiptDate", ""),
#                     "ReceiptTime": receipt.get("receiptTime", ""),
#                     "TotalItems": receipt.get("totalItems", ""),
#                     "DiningOptions": receipt.get("diningOptions", ""),
#                     "PaymentType": receipt.get("paymentType", ""),
#                     "CreditCardType": receipt.get("creditCardType", ""),
#                     "TotalDiscount": receipt.get("totalDiscount", 0.0),
#                     "Tax": receipt.get("tax", 0.0),
#                     "Total": receipt.get("total", 0.0),
#                     "Description": item.get("description", ""),
#                     "UnabbreviatedDescription": item.get("unabbreviatedDescription", ""),
#                     "IncludedItems": ", ".join(item.get("includedItems", [])),
#                     "Quantity": item.get("quantity", 0),
#                     "UnitPrice": item.get("unitPrice", 0.0),
#                     "TotalPrice": item.get("totalPrice", 0.0),
#                     "DiscountAmount": item.get("discountAmount", 0.0)
#                 })
#
#         except Exception as e:
#             print(f"Error processing file {file.filename}: {str(e)}")
#             continue  # Continue with next file even if one fails
#
#         finally:
#             # Clean up temporary files
#             if os.path.exists(temp_path):
#                 os.remove(temp_path)
#             # Add any other cleanup here for 'cleaned_path' if needed
#
#     # After processing all files, save all data to Excel
#     if all_rows:
#         df = pd.DataFrame(all_rows)
#
#         # Check if Excel file already exists
#         if os.path.exists(EXCEL_PATH):
#             # Append to existing file (create new sheet with timestamp)
#             with pd.ExcelWriter(EXCEL_PATH, mode='a', engine='openpyxl') as writer:
#                 sheet_name = f"Receipts_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
#                 df.to_excel(writer, sheet_name=sheet_name, index=False)
#         else:
#             # Create new Excel file
#             df.to_excel(EXCEL_PATH, index=False)
#
#         return {
#             "message": "Success",
#             "processed_files": len(files),
#             "total_items": len(all_rows),
#             "excel_url": "/download"
#         }
#     else:
#         raise HTTPException(
#             status_code=400,
#             detail="No valid receipt data could be extracted from the uploaded files."
#         )

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

    # ✅ Rate limit check
    if db.query(UploadLog).filter(UploadLog.ip == ip_address, UploadLog.upload_date == today).count() >= 3:
        raise HTTPException(status_code=403, detail="Free daily upload limit (3) reached.")

    all_rows = []

    for file in files:
        try:
            contents = await file.read()
            file_hash = compute_sha256(contents)

            # ✅ Check cache
            cached = db.query(CachedResult).filter(CachedResult.file_hash == file_hash).first()
            if cached:
                parsed = json.loads(cached.json_data)
                source = "cache"
            else:
                # Save temp file
                temp_path = os.path.join(UPLOAD_FOLDER, f"temp_{uuid.uuid4().hex}.png")
                with open(temp_path, "wb") as f:
                    f.write(contents)

                # OCR
                extracted_text = extract_google_text(contents)

                # Save JSON via DeepSeek
                json_path = os.path.join(JSON_FOLDER, f"{uuid.uuid4().hex}.json")
                await parse_with_deepseek(extracted_text, json_path)

                # Read and sanitize JSON
                with open(json_path) as f:
                    raw = f.read()
                try:
                    parsed = json.loads(raw)
                except:
                    parsed = json.loads(sanitize_json_string(raw))

                # ✅ Cache result
                db.add(CachedResult(file_hash=file_hash, json_data=json.dumps(parsed)))
                db.commit()

                # Cleanup
                os.remove(temp_path)
                source = "deepseek"

            # ✅ Log usage
            db.add(UploadLog(ip=ip_address, upload_date=today))
            db.commit()

            # Extract structured rows
            receipt = parsed.get("ReceiptInfo", {})
            items = receipt.get("ITEMS", [])
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

        except Exception as e:
            print(f"Error processing file {file.filename}: {str(e)}")
            continue

    # ✅ Save to Excel
    if all_rows:
        df = pd.DataFrame(all_rows)
        if os.path.exists(EXCEL_PATH):
            with pd.ExcelWriter(EXCEL_PATH, mode='a', engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name=f"Receipts_{pd.Timestamp.now():%Y%m%d_%H%M%S}", index=False)
        else:
            df.to_excel(EXCEL_PATH, index=False)

        return {
            "message": "Success",
            "processed_files": len(files),
            "total_items": len(all_rows),
            "source": source,
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