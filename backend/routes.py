"""The app's own API: receipts, exports and analytics. Replaces the Supabase edge functions, RPCs and direct table reads."""
import csv
import io
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from auth import get_current_user, user_json
from database import Receipt, User, get_db
from processing import extract_receipt, summarize

router = APIRouter()

FREE_FILE_LIMIT = int(os.getenv("FREE_FILE_LIMIT", "10"))
MAX_FILES_PER_REQUEST = int(os.getenv("MAX_FILES_PER_REQUEST", "10"))
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_MB", "10")) * 1024 * 1024
MAX_FILES_PER_HOUR = int(os.getenv("MAX_FILES_PER_HOUR", "60"))
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff", "application/pdf"}

# Per-user hourly cap so even a premium account can't run up the OCR/LLM bill.
# In memory: fine for one instance; it resets on restart.
_recent_uploads: Dict[str, deque] = defaultdict(deque)


def _check_hourly_limit(user_id: str, count: int) -> None:
    now = time.time()
    window = _recent_uploads[user_id]
    while window and now - window[0] > 3600:
        window.popleft()
    if len(window) + count > MAX_FILES_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many uploads this hour. Please try again later.")
    window.extend([now] * count)


# ---------- Auth ----------


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return user_json(user)


# ---------- Receipts ----------


def receipt_json(r: Receipt) -> dict:
    # Field names match the old Supabase `processed_files` rows the React app reads.
    return {
        "id": r.id,
        "file_name": r.original_file_name,
        "original_file_name": r.original_file_name,
        "file_size": r.file_size,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "status": r.status,
        "merchant": r.merchant,
        "total": r.total,
        "item_count": r.item_count,
        "category": r.category,
        "confidence_score": None,
        "expires_at": None,
        "processed_data": json.loads(r.data_json) if r.data_json else None,
    }


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def merge_receipts(results: List[dict]) -> dict:
    """Same 'mergedData' shape the old process-receipt edge function returned."""
    return {
        "summary": {
            "totalFiles": len(results),
            "totalAmount": f"{sum(_to_float(r['total']) for r in results):.2f}",
            "totalItems": sum(len(r["items"]) for r in results),
            "processedAt": datetime.now(timezone.utc).isoformat(),
        },
        "receipts": results,
        "combinedItems": [
            {
                "receiptNumber": i + 1,
                "merchant": r["merchant"],
                "date": r["date"],
                "description": item.get("description") or "Unknown Item",
                "amount": item.get("amount", 0),
                "category": item.get("category") or r["category"],
                "fileName": r["fileName"],
            }
            for i, r in enumerate(results)
            for item in r["items"]
        ],
    }


@router.post("/receipts")
async def upload_receipts(
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=413, detail=f"At most {MAX_FILES_PER_REQUEST} files at a time.")
    if user.tier != "premium" and user.files_used + len(files) > FREE_FILE_LIMIT:
        left = max(0, FREE_FILE_LIMIT - user.files_used)
        detail = (
            f"You have used all {FREE_FILE_LIMIT} free files. Please upgrade to Premium for unlimited uploads."
            if left == 0
            else f"Your free plan has {left} file{'s' if left != 1 else ''} left. Remove some files or upgrade to Premium."
        )
        raise HTTPException(status_code=403, detail=detail)
    _check_hourly_limit(user.id, len(files))

    results, failed = [], []
    for upload in files:
        contents = await upload.read()
        if len(contents) > MAX_FILE_BYTES:
            failed.append({"fileName": upload.filename, "error": "File is too large"})
            continue
        if upload.content_type and upload.content_type not in ALLOWED_TYPES:
            failed.append({"fileName": upload.filename, "error": "Unsupported file type"})
            continue

        try:
            summary = summarize(await extract_receipt(contents, db))
        except Exception as e:
            print(f"Error processing upload for user {user.id}: {type(e).__name__}: {str(e)[:300]}", flush=True)
            failed.append({"fileName": upload.filename, "error": "Could not read this receipt"})
            continue

        category = next((i["category"] for i in summary["items"] if i.get("category")), "") or "uncategorized"
        receipt = Receipt(
            user_id=user.id,
            original_file_name=upload.filename,
            file_size=len(contents),
            status="completed",
            merchant=summary["merchant"] or "Unknown Merchant",
            receipt_date=summary["date"] or None,
            total=_to_float(summary["total"]),
            item_count=len(summary["items"]),
            category=category,
        )
        db.add(receipt)
        db.flush()  # assigns receipt.id
        processed = {
            "fileId": receipt.id,
            "fileName": upload.filename,
            "merchant": receipt.merchant,
            "date": summary["date"],
            "total": f"{receipt.total:.2f}",
            "items": summary["items"],
            "category": category,
        }
        receipt.data_json = json.dumps(processed)
        user.files_used += 1
        db.commit()
        results.append(processed)

    if not results:
        detail = failed[0]["error"] if failed else "No receipt could be processed."
        raise HTTPException(status_code=422, detail=detail)

    merged = merge_receipts(results)
    return {"receipts": results, "failed": failed, "mergedData": merged, "summary": merged["summary"]}


@router.get("/receipts")
def list_receipts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Receipt).filter(Receipt.user_id == user.id).order_by(Receipt.created_at.desc()).all()
    return {"receipts": [receipt_json(r) for r in rows], "files_used": user.files_used, "tier": user.tier}


def _owned_receipts(db: Session, user: User, ids: Optional[str]) -> List[Receipt]:
    q = db.query(Receipt).filter(Receipt.user_id == user.id, Receipt.status == "completed")
    if ids:
        wanted = [i for i in ids.split(",") if i]
        q = q.filter(Receipt.id.in_(wanted))
    return q.order_by(Receipt.created_at).all()


EXPORT_COLUMNS = ["Receipt", "File", "Merchant", "Date", "Receipt Total", "Description", "Amount", "Category"]


def _export_rows(receipts: List[Receipt]) -> List[list]:
    rows = []
    for n, r in enumerate(receipts, start=1):
        data = json.loads(r.data_json or "{}")
        items = data.get("items") or [{}]
        for item in items:
            rows.append([
                n,
                r.original_file_name or "",
                r.merchant or "",
                r.receipt_date or "",
                r.total if r.total is not None else "",
                item.get("description", ""),
                _to_float(item.get("amount")) if item else "",
                item.get("category") or r.category or "",
            ])
    return rows


@router.get("/receipts/export")
def export_receipts(
    format: str = Query("csv", pattern="^(csv|xlsx|json)$"),
    ids: Optional[str] = Query(None, description="Comma-separated receipt ids; all receipts if omitted"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if format in ("xlsx", "json") and user.tier != "premium":
        raise HTTPException(status_code=403, detail="Excel and JSON exports are available on Premium.")
    receipts = _owned_receipts(db, user, ids)
    if not receipts:
        raise HTTPException(status_code=404, detail="No processed receipts to export.")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if format == "json":
        body = json.dumps([json.loads(r.data_json or "{}") for r in receipts], indent=2)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="receipts-{stamp}.json"'})

    rows = _export_rows(receipts)
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(EXPORT_COLUMNS)
        writer.writerows(rows)
        # BOM so Excel opens UTF-8 (e.g. ₹, accented merchant names) correctly
        return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="receipts-{stamp}.csv"'})

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Receipts"
    ws.append(EXPORT_COLUMNS)
    for row in rows:
        ws.append(row)
    for col, width in zip("ABCDEFGH", (9, 24, 28, 14, 14, 40, 12, 18)):
        ws.column_dimensions[col].width = width
    out = io.BytesIO()
    wb.save(out)
    return Response(out.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="receipts-{stamp}.xlsx"'})


@router.get("/receipts/{receipt_id}")
def get_receipt(receipt_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return receipt_json(r)


@router.delete("/receipts/{receipt_id}")
def delete_receipt(receipt_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Receipt not found")
    db.delete(r)
    db.commit()
    return {"deleted": receipt_id}


# ---------- Analytics ----------

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y")


def _month_of(r: Receipt) -> str:
    text = (r.receipt_date or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    return r.created_at.strftime("%Y-%m")


@router.get("/analytics")
def analytics(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.tier != "premium":
        raise HTTPException(status_code=403, detail="Analytics is a Premium feature.")
    totals: Dict[tuple, list] = defaultdict(lambda: [0.0, 0])
    for r in db.query(Receipt).filter(Receipt.user_id == user.id, Receipt.status == "completed"):
        key = (_month_of(r), r.category or "uncategorized")
        totals[key][0] += r.total or 0.0
        totals[key][1] += 1
    rows = [
        {"month_year": m, "category": c, "total_amount": round(t, 2), "transaction_count": n}
        for (m, c), (t, n) in totals.items()
    ]
    rows.sort(key=lambda x: (x["month_year"], x["category"]), reverse=True)
    return {"analytics": rows}
