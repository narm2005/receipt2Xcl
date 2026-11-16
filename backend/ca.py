"""'Send to my CA': the accountant's contact, private download links for WhatsApp, and email."""
import base64
import html
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user
from database import CaContact, EmailLog, Receipt, ShareLink, User, get_db
from routes import build_export
from settings import get_settings, money

router = APIRouter()

LINK_DAYS = int(os.getenv("SHARE_LINK_DAYS", "7"))
CA_EMAILS_PER_DAY = int(os.getenv("CA_EMAILS_PER_DAY", "10"))
BREVO_URL = "https://api.brevo.com/v3/smtp/email"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def email_configured() -> bool:
    return bool(os.getenv("BREVO_API_KEY") and os.getenv("MAIL_FROM_EMAIL"))


def normalize_whatsapp(raw: str) -> str:
    """Digits with country code, as wa.me wants them. A 10-digit number is taken as Indian (+91)."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    if not 11 <= len(digits) <= 15:
        raise HTTPException(status_code=422, detail="Enter the WhatsApp number as 10 digits, or with the country code.")
    return digits


# ---------- The CA's contact ----------


class CaIn(BaseModel):
    name: str = Field("", max_length=120)
    whatsapp: str = Field("", max_length=30)
    email: str = Field("", max_length=320)


def ca_json(c) -> dict:
    return {
        "name": (c.name if c else "") or "",
        "whatsapp": (c.whatsapp if c else "") or "",
        "email": (c.email if c else "") or "",
        "email_enabled": email_configured(),
    }


@router.get("/settings/ca")
def get_ca(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ca_json(db.get(CaContact, user.id))


@router.put("/settings/ca")
def save_ca(body: CaIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    email = body.email.strip()
    if email and not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="That email address doesn't look right.")
    c = db.get(CaContact, user.id) or CaContact(user_id=user.id)
    c.name = body.name.strip() or None
    c.whatsapp = normalize_whatsapp(body.whatsapp) or None
    c.email = email or None
    db.merge(c)
    db.commit()
    return ca_json(c)


# ---------- What to send ----------


class SendIn(BaseModel):
    ids: List[str] = Field(..., min_length=1, max_length=2000)
    label: str = Field("", max_length=40)  # e.g. "Oct 2026"


def _receipts(db: Session, user: User, ids: List[str]) -> List[Receipt]:
    rows = (
        db.query(Receipt)
        .filter(Receipt.user_id == user.id, Receipt.status == "completed", Receipt.id.in_(ids))
        .order_by(Receipt.created_at)
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No processed receipts to send.")
    return rows


def _format(user: User) -> str:
    # Premium gets Excel with the GST summary sheet; free gets CSV.
    return "xlsx" if user.tier == "premium" else "csv"


def _stamp(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    return slug or datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _public_base(request: Request) -> str:
    configured = os.getenv("PUBLIC_API_URL")
    if configured:
        return configured.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{proto}://{request.headers.get('host', request.url.netloc)}"


# ---------- WhatsApp: a private link the CA can open ----------


@router.post("/ca/link")
def create_link(body: SendIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """WhatsApp links can't carry a file, so the message carries a private download link instead.
    The link is unguessable, works only for these receipts, and expires after SHARE_LINK_DAYS."""
    receipts = _receipts(db, user, body.ids)
    link = ShareLink(
        token=secrets.token_urlsafe(24),
        user_id=user.id,
        receipt_ids=",".join(r.id for r in receipts),
        format=_format(user),
        label=body.label.strip() or None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=LINK_DAYS),
    )
    db.add(link)
    db.commit()
    return {"url": f"{_public_base(request)}/s/{link.token}", "expires_at": link.expires_at.isoformat(), "days": LINK_DAYS}


@router.get("/s/{token}")
def open_link(token: str, db: Session = Depends(get_db)):
    link = db.get(ShareLink, token) if len(token) <= 64 else None
    if not link or _utc(link.expires_at) < datetime.now(timezone.utc):
        return PlainTextResponse("This link has expired or doesn't exist. Please ask for a new one.", status_code=404)
    ids = [i for i in link.receipt_ids.split(",") if i]
    receipts = (
        db.query(Receipt)
        .filter(Receipt.user_id == link.user_id, Receipt.status == "completed", Receipt.id.in_(ids))
        .order_by(Receipt.created_at)
        .all()
    )
    if not receipts:
        return PlainTextResponse("These receipts are no longer available.", status_code=404)
    content, media_type, filename = build_export(receipts, link.format, _stamp(link.label or ""))
    return Response(content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex",
    })


# ---------- Email: sent only after the user confirms in the app ----------


def send_email(payload: dict) -> None:
    r = requests.post(BREVO_URL, json=payload, timeout=20,
                      headers={"api-key": os.environ["BREVO_API_KEY"], "accept": "application/json"})
    if r.status_code >= 300:
        print(f"Brevo send failed: {r.status_code} {r.text[:300]}", flush=True)
        raise HTTPException(status_code=502, detail="Could not send the email. Please try again later.")


@router.post("/ca/email")
def email_ca(body: SendIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not email_configured():
        raise HTTPException(status_code=503, detail="Email sending isn't set up yet. Use WhatsApp or Share instead.")
    ca = db.get(CaContact, user.id)
    if not ca or not ca.email:
        raise HTTPException(status_code=400, detail="Add your CA's email in Settings first.")
    since = datetime.now(timezone.utc) - timedelta(days=1)
    sent_today = db.query(EmailLog).filter(EmailLog.user_id == user.id, EmailLog.sent_at >= since).count()
    if sent_today >= CA_EMAILS_PER_DAY:
        raise HTTPException(status_code=429, detail=f"You can send {CA_EMAILS_PER_DAY} emails a day. Please try again tomorrow.")

    receipts = _receipts(db, user, body.ids)
    label = body.label.strip()
    content, _, filename = build_export(receipts, _format(user), _stamp(label))
    sender_name = user.name or user.email or "A SlickReceipts user"
    total = sum(r.total or 0 for r in receipts)
    what = f"{label} bills" if label else "bills"
    payload = {
        "sender": {"email": os.environ["MAIL_FROM_EMAIL"], "name": os.getenv("MAIL_FROM_NAME") or "SlickReceipts"},
        "to": [{"email": ca.email, **({"name": ca.name} if ca.name else {})}],
        "subject": f"{what.capitalize()} from {sender_name}",
        "htmlContent": (
            f"<p>Hello{(' ' + html.escape(ca.name)) if ca.name else ''},</p>"
            f"<p>{html.escape(sender_name)} has sent you {len(receipts)} {html.escape(what)} "
            f"(total {html.escape(money(total, get_settings(db)['currency']))}). The file is attached.</p>"
            f"<p>Reply to this email to reach {html.escape(sender_name)} directly.</p>"
            "<p>Sent with SlickReceipts</p>"
        ),
        "attachment": [{"content": base64.b64encode(content).decode(), "name": filename}],
    }
    if user.email:
        payload["replyTo"] = {"email": user.email}
        payload["cc"] = [{"email": user.email}]  # the user gets a copy of what was sent
    send_email(payload)
    db.add(EmailLog(user_id=user.id, to_email=ca.email))
    db.commit()
    return {"sent_to": ca.email, "receipts": len(receipts)}
