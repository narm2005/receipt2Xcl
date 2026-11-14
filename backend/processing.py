"""Receipt image -> structured data (Google Vision OCR, then DeepSeek), with a cache by file hash."""
import hashlib
import json
import os
import re
import tempfile

from google.cloud import vision
from sqlalchemy.orm import Session

import convert
from database import CachedResult


def _setup_google_credentials() -> None:
    raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not raw:
        raise RuntimeError("Environment variable GOOGLE_APPLICATION_CREDENTIALS_JSON must be set")
    # The Google client library wants a file path, so write the JSON from the env var to a temp file.
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as temp:
        json.dump(json.loads(raw), temp)
        temp.flush()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp.name


_setup_google_credentials()


def compute_sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def sanitize_json_string(raw: str) -> str:
    raw = raw.strip().strip("```json").strip("```")
    raw = raw.replace("'", '"')
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    raw = re.sub(r'(?<={|,)\s*(\w+)\s*:', r'"\1":', raw)
    return raw


def extract_google_text(content: bytes) -> str:
    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=content)
    response = client.text_detection(image=image)
    if response.error.message:
        raise RuntimeError(f"Vision API error: {response.error.message}")
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
    if not extracted_text.strip():
        raise ValueError("No text found in the image")
    parsed = await parse_with_deepseek(extracted_text)
    db.add(CachedResult(file_hash=file_hash, json_data=json.dumps(parsed)))
    db.commit()
    return parsed


def summarize(parsed: dict) -> dict:
    """The compact shape the frontend uses: merchant, date, total, items[description, amount, category]."""
    receipt = parsed.get("ReceiptInfo", {})
    items = receipt.get("ITEMS", [])
    return {
        "merchant": receipt.get("merchant", ""),
        "date": receipt.get("receiptDate", ""),
        "total": receipt.get("total", 0.0),
        "items": [
            {
                "description": item.get("unabbreviatedDescription") or item.get("description", ""),
                "amount": item.get("totalPrice", 0.0),
                "category": item.get("category", ""),
            }
            for item in items
        ],
    }
