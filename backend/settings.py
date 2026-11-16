"""Admin-editable settings: currency and Premium prices, plus switching users between Free and Premium.

Admins are the signed-in users whose email is listed in ADMIN_EMAILS (comma-separated) on the server.
"""
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from auth import get_current_user
from database import AppSetting, Receipt, User, get_db

router = APIRouter()

CURRENCIES = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "AED": "AED ", "SGD": "S$", "AUD": "A$", "CAD": "C$"}
DEFAULTS = {
    "currency": os.getenv("DEFAULT_CURRENCY", "INR"),
    "premium_monthly": 199,
    "premium_yearly": 1999,
}


def admin_emails() -> set:
    return {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


def is_admin(user: User) -> bool:
    return bool(user.email) and user.email.lower() in admin_emails()


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admins only.")
    return user


def get_settings(db: Session) -> dict:
    values = dict(DEFAULTS)
    for row in db.query(AppSetting).filter(AppSetting.key.in_(list(DEFAULTS))):
        try:
            values[row.key] = json.loads(row.value)
        except ValueError:
            pass
    return values


def money(amount: float, currency: str) -> str:
    return f"{CURRENCIES.get(currency, currency + ' ')}{amount:,.2f}"


def public_config(db: Session) -> dict:
    s = get_settings(db)
    return {**s, "currency_symbol": CURRENCIES.get(s["currency"], s["currency"] + " ").strip(), "currencies": list(CURRENCIES)}


@router.get("/config")
def config(db: Session = Depends(get_db)):
    """Public: what the Pricing page and amounts use."""
    return public_config(db)


class ConfigIn(BaseModel):
    currency: str = Field(..., min_length=3, max_length=3)
    premium_monthly: float = Field(..., ge=0, le=1_000_000)
    premium_yearly: float = Field(..., ge=0, le=10_000_000)


@router.put("/admin/config")
def save_config(body: ConfigIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    currency = body.currency.upper()
    if currency not in CURRENCIES:
        raise HTTPException(status_code=422, detail=f"Currency must be one of {', '.join(CURRENCIES)}.")
    for key, value in (("currency", currency), ("premium_monthly", round(body.premium_monthly, 2)),
                       ("premium_yearly", round(body.premium_yearly, 2))):
        row = db.get(AppSetting, key) or AppSetting(key=key)
        row.value = json.dumps(value)
        row.updated_by = admin.email
        db.merge(row)
    db.commit()
    print(f"Settings changed by {admin.email}: {currency} {body.premium_monthly}/{body.premium_yearly}", flush=True)
    return public_config(db)


# ---------- Users ----------


def _user_row(db: Session, u: User) -> dict:
    count = db.query(func.count(Receipt.id)).filter(Receipt.user_id == u.id).scalar() or 0
    return {"id": u.id, "email": u.email, "name": u.name, "tier": u.tier, "files_used": u.files_used,
            "receipts": count, "created_at": u.created_at.isoformat() if u.created_at else None}


@router.get("/admin/users")
def list_users(q: Optional[str] = Query(None, max_length=100), admin: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    query = db.query(User)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.filter(or_(func.lower(User.email).like(like), func.lower(User.name).like(like)))
    users = query.order_by(User.created_at.desc()).limit(50).all()
    return {
        "users": [_user_row(db, u) for u in users],
        "totals": {
            "users": db.query(func.count(User.id)).scalar(),
            "premium": db.query(func.count(User.id)).filter(User.tier == "premium").scalar(),
        },
    }


class TierIn(BaseModel):
    tier: str = Field(..., pattern="^(freemium|premium)$")


@router.patch("/admin/users/{user_id}")
def set_tier(user_id: str, body: TierIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.tier = body.tier
    db.commit()
    print(f"{admin.email} set {u.email} to {body.tier}", flush=True)
    return _user_row(db, u)
