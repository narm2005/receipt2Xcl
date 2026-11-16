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


class NotAReceipt(ValueError):
    """The upload is readable but is not a bill or receipt (a selfie, a screenshot, a page of text...)."""

    message = "This doesn't look like a receipt or bill. Please upload a clear photo of the bill."


# Words that appear on almost every bill, in English and a few Indian languages.
RECEIPT_WORDS = re.compile(
    r"\b(total|sub ?total|grand total|amount|amt|qty|quantity|rate|price|mrp|bill|invoice|receipt|cash|card|upi|"
    r"paid|change|balance|tax|gst|gstin|cgst|sgst|igst|vat|net|discount|item|items|rs\.?|inr|order|payment|txn)\b"
    r"|₹|कुल|बिल|रसीद|மொத்தம்|ரசீது|మొత్తం|ಒಟ್ಟು|മൊത്തം",
    re.IGNORECASE,
)
PRICE = re.compile(r"\d+[.,]\d{2}\b")
REJECTED = {"not_receipt": True}


def looks_like_receipt_text(text: str) -> bool:
    """Cheap check on the OCR text before paying for the LLM: a bill has bill words or several prices."""
    text = text or ""
    if len(text.strip()) < 8:
        return False
    words = len(RECEIPT_WORDS.findall(text))
    prices = len(PRICE.findall(text))
    return words >= 2 or (words >= 1 and bool(re.search(r"\d{2,}", text))) or prices >= 3


def has_receipt_data(parsed: dict) -> bool:
    """After structuring: a receipt has a total or at least one priced item."""
    info = (parsed or {}).get("ReceiptInfo") or {}
    try:
        total = float(info.get("total") or 0)
    except (TypeError, ValueError):
        total = 0.0
    priced = [i for i in info.get("ITEMS") or [] if _num(i.get("totalPrice")) > 0]
    return total > 0 or bool(priced)


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


async def extract_receipt(contents: bytes, db: Session) -> dict:
    """OCR + structure one receipt, using the cache so the same image is never paid for twice.
    Raises NotAReceipt for photos that aren't bills, and remembers them so a retry costs nothing."""
    file_hash = compute_sha256(contents)
    cached = db.query(CachedResult).filter(CachedResult.file_hash == file_hash).first()
    if cached:
        parsed = json.loads(cached.json_data)
        if parsed == REJECTED:
            raise NotAReceipt()
        return parsed

    extracted_text = extract_google_text(contents)
    if not extracted_text.strip() or not looks_like_receipt_text(extracted_text):
        _remember(db, file_hash, REJECTED)
        raise NotAReceipt()
    parsed = await parse_with_deepseek(extracted_text)
    if not has_receipt_data(parsed):
        _remember(db, file_hash, REJECTED)
        raise NotAReceipt()
    _remember(db, file_hash, parsed)
    return parsed


def _remember(db: Session, file_hash: str, parsed: dict) -> None:
    db.add(CachedResult(file_hash=file_hash, json_data=json.dumps(parsed)))
    db.commit()


def summarize(parsed: dict) -> dict:
    """The compact shape the frontend uses: merchant, date, total, items[description, amount, category]."""
    receipt = parsed.get("ReceiptInfo", {})
    items = receipt.get("ITEMS", [])
    return {
        "merchant": receipt.get("merchant", ""),
        "date": receipt.get("receiptDate", ""),
        "total": receipt.get("total", 0.0),
        "gstin": (receipt.get("gstin") or "").upper().replace(" ", ""),
        "invoiceNumber": receipt.get("invoiceNumber") or "",
        "cgst": receipt.get("cgst") or 0.0,
        "sgst": receipt.get("sgst") or 0.0,
        "igst": receipt.get("igst") or 0.0,
        "items": [
            {
                "description": item.get("unabbreviatedDescription") or item.get("description", ""),
                "amount": item.get("totalPrice", 0.0),
                "category": item.get("category", ""),
            }
            for item in items
        ],
    }
