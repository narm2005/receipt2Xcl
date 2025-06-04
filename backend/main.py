# Enhanced receipt processing API with all improvements
import cv2
import numpy as np
import json
import re
import uuid
import os
import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, status, Request, Header
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.security import APIKeyHeader
from slowapi import Limiter
from slowapi.util import get_remote_address
from dotenv import load_dotenv
from PIL import Image

from paddleocr import PaddleOCR
from transformers import LayoutLMv3Processor, LayoutLMv3ForTokenClassification
import torch

# Local imports
from ocr_utils import ocr_image_multilang, easyocr_image_multilang
import convert

# Load configuration
load_dotenv()

# Constants
CONFIG = {
    "MAX_FILE_SIZE": 5 * 1024 * 1024,  # 5MB
    "ALLOWED_FILE_TYPES": [".png", ".jpg", ".jpeg"],
    "MAX_FILES_PER_REQUEST": 10,
    "API_RATE_LIMIT": "100/minute",
    "TEMP_DIR": "temp",
    "OUTPUT_DIR": "output",
    "LOG_FILE": "receipt_processor.log"
}

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(CONFIG["LOG_FILE"]),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Initialize models
def initialize_models():
    """Initialize all ML models with error handling"""
    try:
        ocr_engine = PaddleOCR(use_angle_cls=True, lang='en')
        processor = LayoutLMv3Processor.from_pretrained("microsoft/layoutlmv3-base")
        layout_model = LayoutLMv3ForTokenClassification.from_pretrained("microsoft/layoutlmv3-base")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        layout_model.to(device)
        return ocr_engine, processor, layout_model
    except Exception as e:
        logger.error(f"Model initialization failed: {str(e)}")
        raise


ocr_engine, processor, layout_model = initialize_models()

# API Configuration
app = FastAPI(
    title="Receipt Processing API",
    description="API for extracting structured data from receipt images",
    version="1.0.0"
)

# Security
api_key_header = APIKeyHeader(name="X-API-Key")

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create required directories
Path(CONFIG["TEMP_DIR"]).mkdir(exist_ok=True)
Path(CONFIG["OUTPUT_DIR"]).mkdir(exist_ok=True)


# Helper functions
def validate_api_key(api_key: str):
    """Validate the API key"""
    if api_key != os.getenv("API_KEY"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )


def preprocess_image(image_path: str) -> str:
    """Enhanced image preprocessing with error handling"""
    try:
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError("Failed to read image file")

        img = cv2.GaussianBlur(img, (3, 3), 0)
        _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        cleaned_path = os.path.join(CONFIG["TEMP_DIR"], f"cleaned_{uuid.uuid4().hex}.png")
        cv2.imwrite(cleaned_path, img)
        return cleaned_path
    except Exception as e:
        logger.error(f"Image preprocessing failed: {str(e)}")
        raise


def sanitize_json_string(raw: str) -> str:
    """Robust JSON sanitizer with multiple fallbacks"""
    try:
        # Remove Markdown code block if any
        raw = raw.strip().strip("```json").strip("```")

        # Common fixes
        raw = raw.replace("'", '"')  # Single to double quotes
        raw = re.sub(r",\s*([}\]])", r"\1", raw)  # Trailing commas
        raw = re.sub(r'(?<={|,)\s*(\w+)\s*:', r'"\1":', raw)  # Unquoted keys

        # Try parsing to validate
        json.loads(raw)
        return raw
    except json.JSONDecodeError as e:
        logger.warning(f"JSON sanitization failed, attempting fallback: {str(e)}")
        # Fallback: Extract the first valid JSON object
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return match.group()
        raise ValueError("No valid JSON found in response")


async def generate_excel_report(results: List[Dict[str, Any]]) -> str:
    """Generate Excel report from processed results"""
    try:
        rows = []
        for result in results:
            if result["status"] != "success":
                continue

            receipt = result["data"].get("ReceiptInfo", {})
            items = receipt.get("ITEMS", [])

            for item in items:
                rows.append({
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

        if not rows:
            raise ValueError("No valid receipt data to export")

        df = pd.DataFrame(rows)
        excel_path = os.path.join(CONFIG["OUTPUT_DIR"], "structured_receipts.xlsx")
        df.to_excel(excel_path, index=False)
        return excel_path
    except Exception as e:
        logger.error(f"Excel report generation failed: {str(e)}")
        raise


# API Endpoints
@app.post("/upload")
@limiter.limit(CONFIG["API_RATE_LIMIT"])
async def upload_receipts(
        request: Request,
        files: List[UploadFile] = File(...),
        lang: Optional[str] = Form('en'),  # Default value added
        auto_detect: Optional[bool] = Form(False),  # Default value added
        x_api_key: Optional[str] = Header(None)  # Make API key optional if you want
):
    """
    Process uploaded receipt images and extract structured data.

    Parameters:
    - files: List of receipt images (PNG/JPG) (required)
    - lang: Language code for OCR (default: 'en')
    - auto_detect: Whether to auto-detect language (default: False)
    - x_api_key: API key for authentication (optional if not in production)
    """
    # # Authentication (if enabled)
    # if os.getenv("REQUIRE_API_KEY", "true").lower() == "true":
    #     if not x_api_key:
    #         raise HTTPException(
    #             status_code=status.HTTP_401_UNAUTHORIZED,
    #             detail="API key required"
    #         )
    #     validate_api_key(x_api_key)

    # Validate at least one file was uploaded
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file must be uploaded"
        )

    # Rest of your existing implementation...

    if len(files) > CONFIG["MAX_FILES_PER_REQUEST"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {CONFIG['MAX_FILES_PER_REQUEST']} files per request"
        )

    results = []
    temp_files = []

    try:
        for file in files:
            file_result = {
                "filename": file.filename,
                "status": "pending",
                "timestamp": datetime.utcnow().isoformat()
            }

            try:
                # File validation
                file_ext = Path(file.filename).suffix.lower()
                if file_ext not in CONFIG["ALLOWED_FILE_TYPES"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid file type: {file.filename}. Allowed types: {CONFIG['ALLOWED_FILE_TYPES']}"
                    )

                # Check file size
                file.file.seek(0, 2)
                file_size = file.file.tell()
                file.file.seek(0)

                if file_size > CONFIG["MAX_FILE_SIZE"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File too large: {file.filename}. Max size: {CONFIG['MAX_FILE_SIZE']} bytes"
                    )

                # Save uploaded file
                temp_path = os.path.join(CONFIG["TEMP_DIR"], f"temp_{uuid.uuid4().hex}{file_ext}")
                temp_files.append(temp_path)

                with open(temp_path, "wb") as f:
                    f.write(await file.read())

                # Process image
                logger.info(f"Processing file: {file.filename}")
                extracted_text = ocr_image_multilang(
                    temp_path,
                    lang=lang,
                    auto_detect=auto_detect
                )

                # Parse with LLM
                json_path = os.path.join(CONFIG["OUTPUT_DIR"], f"{uuid.uuid4().hex}.json")
                await parse_with_deepseek(extracted_text, json_path)

                # Read and validate parsed data
                with open(json_path) as f:
                    parsed_data = json.load(f)

                file_result.update({
                    "status": "success",
                    "data": parsed_data,
                    "processing_time": datetime.utcnow().isoformat()
                })

            except Exception as e:
                logger.error(f"Error processing {file.filename}: {str(e)}")
                file_result.update({
                    "status": "error",
                    "error": str(e),
                    "processing_time": datetime.utcnow().isoformat()
                })

            results.append(file_result)

        # Generate Excel report if any successful results
        if any(r["status"] == "success" for r in results):
            excel_path = await generate_excel_report(results)
            return JSONResponse({
                "status": "complete",
                "success_count": sum(1 for r in results if r["status"] == "success"),
                "error_count": sum(1 for r in results if r["status"] == "error"),
                "results": results,
                "excel_url": "/download"
            })
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="All files failed processing",
                headers={"X-Error-Details": json.dumps(results)}
            )

    finally:
        # Clean up temp files
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception as e:
                logger.warning(f"Failed to delete temp file {temp_file}: {str(e)}")


@app.get("/download")
async def download_excel():
    """Download the processed Excel file"""
    excel_path = os.path.join(CONFIG["OUTPUT_DIR"], "structured_receipts.xlsx")
    if not os.path.exists(excel_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Excel file not found. Please process receipts first."
        )
    return FileResponse(
        excel_path,
        filename="structured_receipts.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# LLM Processing
async def parse_with_deepseek(text: str, json_path: str) -> dict:
    """Enhanced LLM processing with full error handling"""
    try:
        receiptParser = convert.make_receiptParser()
        fewshot_prompt = convert.make_fewshot_prompt(receiptParser.get_format_instructions())
        model = convert.make_deepseek()
        chain = convert.make_chain(fewshot_prompt, model, receiptParser)

        response = chain.invoke({"input": text})

        with open(json_path, 'w') as fp:
            json.dump({"ReceiptInfo": json.loads(response.model_dump_json())}, fp)

        logger.info(f"Successfully processed receipt to {json_path}")
        return {"status": "success", "path": json_path}

    except Exception as e:
        logger.error(f"LLM processing failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LLM processing failed: {str(e)}"
        )


# Monitoring and metrics (would integrate with Prometheus/OpenTelemetry in production)
@app.middleware("http")
async def monitor_requests(request: Request, call_next):
    start_time = datetime.utcnow()
    response = await call_next(request)
    process_time = (datetime.utcnow() - start_time).total_seconds() * 1000

    logger.info(
        f"Request: {request.method} {request.url} "
        f"Status: {response.status_code} "
        f"Process time: {process_time:.2f}ms"
    )

    return response