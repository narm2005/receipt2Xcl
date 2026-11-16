"""The app's own API: receipts, exports and analytics. Replaces the Supabase edge functions, RPCs and direct table reads."""
import csv
import io
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
import requests
from sqlalchemy.orm import Session

from auth import get_current_user, user_json
from database import Receipt, UsageCounter, User, get_db
from processing import extract_receipt, summarize

router = APIRouter()

FREE_FILE_LIMIT = int(os.getenv("FREE_FILE_LIMIT", "10"))
MAX_FILES_PER_REQUEST = int(os.getenv("MAX_FILES_PER_REQUEST", "20"))
# Fair use, so one account cannot run up the OCR/LLM bill. Counted in India time.
DAILY_FILE_LIMIT = int(os.getenv("DAILY_FILE_LIMIT", "100"))
MONTHLY_FILE_LIMIT = int(os.getenv("MONTHLY_FILE_LIMIT", "1000"))
IST = timezone(timedelta(hours=5, minutes=30))
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


def _periods() -> tuple:
    now = datetime.now(IST)
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")


def usage_json(db: Session, user: User) -> dict:
    day, month = _periods()
    counts = {
        c.period: c.count
        for c in db.query(UsageCounter).filter(UsageCounter.user_id == user.id, UsageCounter.period.in_([day, month]))
    }
    return {
        "day_used": counts.get(day, 0),
        "day_limit": DAILY_FILE_LIMIT,
        "month_used": counts.get(month, 0),
        "month_limit": MONTHLY_FILE_LIMIT,
    }


def _check_fair_use(db: Session, user: User, count: int) -> None:
    u = usage_json(db, user)
    if u["month_used"] + count > u["month_limit"]:
        left = max(0, u["month_limit"] - u["month_used"])
        raise HTTPException(status_code=429, detail=(
            f"You have reached this month's limit of {u['month_limit']} receipts. It resets on the 1st."
            if left == 0 else f"You can scan {left} more receipt{'s' if left != 1 else ''} this month."))
    if u["day_used"] + count > u["day_limit"]:
        left = max(0, u["day_limit"] - u["day_used"])
        raise HTTPException(status_code=429, detail=(
            f"You have reached today's limit of {u['day_limit']} receipts. Please continue tomorrow."
            if left == 0 else f"You can scan {left} more receipt{'s' if left != 1 else ''} today."))


def _add_usage(db: Session, user_id: str) -> None:
    for period in _periods():
        row = db.get(UsageCounter, (user_id, period))
        if row:
            row.count += 1
        else:
            db.add(UsageCounter(user_id=user_id, period=period, count=1))


# ---------- Auth ----------


@router.get("/auth/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {**user_json(user), "usage": usage_json(db, user)}


@router.delete("/auth/me")
def delete_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Deletes the user's receipts and account data. Also removes the Supabase sign-in when
    SUPABASE_SERVICE_ROLE_KEY is set on the server (server only, never in the frontend)."""
    uid = user.id
    db.query(Receipt).filter(Receipt.user_id == uid).delete(synchronize_session=False)
    db.query(UsageCounter).filter(UsageCounter.user_id == uid).delete(synchronize_session=False)
    db.delete(user)
    db.commit()

    sign_in_deleted = False
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    supabase_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    if service_key and supabase_url:
        try:
            r = requests.delete(f"{supabase_url}/auth/v1/admin/users/{uid}", timeout=10,
                                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"})
            sign_in_deleted = r.status_code in (200, 204, 404)
            if not sign_in_deleted:
                print(f"Supabase user delete failed for {uid}: {r.status_code}", flush=True)
        except requests.RequestException as e:
            print(f"Supabase user delete failed for {uid}: {type(e).__name__}", flush=True)
    return {"deleted": True, "sign_in_deleted": sign_in_deleted}


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


GST_KEYS = ("gstin", "invoiceNumber", "cgst", "sgst", "igst")


def _gst_fields(src: dict) -> dict:
    return {
        "gstin": str(src.get("gstin") or "").upper().replace(" ", ""),
        "invoiceNumber": str(src.get("invoiceNumber") or ""),
        "cgst": round(_to_float(src.get("cgst")), 2),
        "sgst": round(_to_float(src.get("sgst")), 2),
        "igst": round(_to_float(src.get("igst")), 2),
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
    _check_fair_use(db, user, len(files))
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
            **_gst_fields(summary),
        }
        receipt.data_json = json.dumps(processed)
        user.files_used += 1
        _add_usage(db, user.id)
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


EXPORT_COLUMNS = ["Receipt", "File", "Merchant", "Date", "Receipt Total", "Description", "Amount", "Category",
                  "Invoice No", "GSTIN", "CGST", "SGST", "IGST"]
GST_COLUMNS = ["Date", "Merchant", "GSTIN", "Invoice No", "Taxable Value", "CGST", "SGST", "IGST", "Total", "File"]


def _gst_summary_rows(receipts: List[Receipt]) -> List[list]:
    rows = []
    for r in receipts:
        g = _gst_fields(json.loads(r.data_json or "{}"))
        total = r.total or 0.0
        tax = g["cgst"] + g["sgst"] + g["igst"]
        rows.append([r.receipt_date or "", r.merchant or "", g["gstin"], g["invoiceNumber"],
                     round(total - tax, 2), g["cgst"], g["sgst"], g["igst"], round(total, 2),
                     r.original_file_name or ""])
    return rows


def _export_rows(receipts: List[Receipt]) -> List[list]:
    rows = []
    for n, r in enumerate(receipts, start=1):
        data = json.loads(r.data_json or "{}")
        items = data.get("items") or [{}]
        g = _gst_fields(data)
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
                g["invoiceNumber"], g["gstin"], g["cgst"], g["sgst"], g["igst"],
            ])
    return rows


@router.get("/receipts/export")
def export_receipts(
    format: str = Query("csv", pattern="^(csv|xlsx|json)$"),
    ids: Optional[str] = Query(None, description="Comma-separated receipt ids; all receipts if omitted"),
    month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$", description="Only receipts dated in this month, e.g. 2026-11"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if format in ("xlsx", "json") and user.tier != "premium":
        raise HTTPException(status_code=403, detail="Excel and JSON exports are available on Premium.")
    receipts = _owned_receipts(db, user, ids)
    if month:
        receipts = [r for r in receipts if _month_of(r) == month]
    if not receipts:
        raise HTTPException(status_code=404, detail="No processed receipts to export.")

    stamp = month or datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
    for col, width in zip("ABCDEFGHIJKLM", (9, 24, 28, 14, 14, 40, 12, 18, 16, 18, 10, 10, 10)):
        ws.column_dimensions[col].width = width

    # One row per bill with the GST split: the sheet a CA usually asks for.
    gst = wb.create_sheet("GST summary")
    gst.append(GST_COLUMNS)
    summary = _gst_summary_rows(receipts)
    for row in summary:
        gst.append(row)
    gst.append(["Total", "", "", ""] + [round(sum(r[i] for r in summary), 2) for i in range(4, 9)] + [""])
    for col, width in zip("ABCDEFGHIJ", (14, 28, 18, 16, 14, 10, 10, 10, 12, 24)):
        gst.column_dimensions[col].width = width
    out = io.BytesIO()
    wb.save(out)
    return Response(out.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="receipts-{stamp}.xlsx"'})


class ItemEdit(BaseModel):
    description: str = Field("", max_length=300)
    amount: float = 0.0
    category: str = Field("", max_length=100)


class ReceiptEdit(BaseModel):
    merchant: Optional[str] = Field(None, max_length=255)
    date: Optional[str] = Field(None, max_length=40)
    total: Optional[float] = None
    category: Optional[str] = Field(None, max_length=100)
    gstin: Optional[str] = Field(None, max_length=20)
    invoiceNumber: Optional[str] = Field(None, max_length=60)
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None
    items: Optional[List[ItemEdit]] = Field(None, max_length=500)


@router.patch("/receipts/{receipt_id}")
def edit_receipt(receipt_id: str, edit: ReceiptEdit, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fix what the scan got wrong before exporting."""
    r = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Receipt not found")
    data = json.loads(r.data_json or "{}")
    changes = edit.model_dump(exclude_unset=True)
    if "items" in changes:
        data["items"] = [i.model_dump() for i in edit.items or []]
        r.item_count = len(data["items"])
    if "merchant" in changes:
        r.merchant = data["merchant"] = (edit.merchant or "").strip() or "Unknown Merchant"
    if "date" in changes:
        data["date"] = (edit.date or "").strip()
        r.receipt_date = data["date"] or None
    if "category" in changes:
        r.category = data["category"] = (edit.category or "").strip() or "uncategorized"
    if "total" in changes:
        r.total = round(edit.total or 0.0, 2)
        data["total"] = f"{r.total:.2f}"
    data.update(_gst_fields({**{k: data.get(k) for k in GST_KEYS}, **{k: v for k, v in changes.items() if k in GST_KEYS}}))
    r.data_json = json.dumps(data)
    db.commit()
    return receipt_json(r)


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

# Indian bills print day first (14/11/2026), so try day-first before US month-first.
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%m/%d/%Y", "%m/%d/%y",
                 "%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%b %d, %Y")


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
