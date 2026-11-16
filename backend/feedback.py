"""Feedback page: store messages (signed in or not) and, if email is set up, forward them to support."""
import html
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import ca
from auth import verify_supabase_token
from database import Feedback, User, get_db

router = APIRouter()

PER_IP_PER_HOUR = int(os.getenv("FEEDBACK_PER_HOUR", "5"))
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CATEGORIES = {"idea", "bug", "question", "praise", "other"}


class FeedbackIn(BaseModel):
    category: str = Field("other", max_length=20)
    rating: Optional[int] = Field(None, ge=1, le=5)
    message: str = Field(..., min_length=3, max_length=4000)
    email: str = Field("", max_length=320)
    page: str = Field("", max_length=200)


def _optional_user(authorization: Optional[str], db: Session) -> Optional[User]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        claims = verify_supabase_token(authorization.split(" ", 1)[1].strip())
    except HTTPException:
        return None
    return db.get(User, claims.get("sub")) if claims.get("sub") else None


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() or (request.client.host if request.client else ""))[:45]


@router.post("/feedback")
def send_feedback(
    body: FeedbackIn,
    request: Request,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    user = _optional_user(authorization, db)
    email = (user.email if user and user.email else body.email.strip()) or None
    if email and not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="That email address doesn't look right.")
    category = body.category if body.category in CATEGORIES else "other"

    ip = _client_ip(request)
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    q = db.query(Feedback).filter(Feedback.created_at >= since)
    q = q.filter(Feedback.user_id == user.id) if user else q.filter(Feedback.ip == ip)
    if q.count() >= PER_IP_PER_HOUR:
        raise HTTPException(status_code=429, detail="Thanks! You've sent a lot of feedback this hour. Please try again later.")

    fb = Feedback(user_id=user.id if user else None, email=email, category=category, rating=body.rating,
                  message=body.message.strip(), page=body.page.strip() or None, ip=ip)
    db.add(fb)
    db.commit()

    # Forward to support by email when Brevo is set up; the message is saved either way.
    support = os.getenv("FEEDBACK_TO_EMAIL")
    if support and ca.email_configured():
        try:
            who = email or "an anonymous visitor"
            ca.send_email({
                "sender": {"email": os.environ["MAIL_FROM_EMAIL"], "name": os.getenv("MAIL_FROM_NAME") or "SlickReceipts"},
                "to": [{"email": support}],
                **({"replyTo": {"email": email}} if email else {}),
                "subject": f"Feedback ({category}{f', {body.rating}/5' if body.rating else ''}) from {who}",
                "htmlContent": (
                    f"<p><strong>From:</strong> {html.escape(who)}"
                    f"{' (Premium)' if user and user.tier == 'premium' else ''}</p>"
                    f"<p style='white-space:pre-wrap'>{html.escape(fb.message)}</p>"
                ),
            })
        except Exception as e:  # never lose feedback because the email failed
            print(f"Feedback email failed: {type(e).__name__}", flush=True)
    return {"ok": True}
