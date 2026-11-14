"""Google sign-in and session tokens. Replaces Supabase Auth."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import User, get_db

JWT_SECRET = os.getenv("JWT_SECRET") or ""
if not JWT_SECRET:
    raise RuntimeError("Environment variable JWT_SECRET must be set")

SESSION_DAYS = int(os.getenv("SESSION_DAYS", "14"))
ALGORITHM = "HS256"


def create_session_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def get_current_user(
    authorization: Optional[str] = Header(None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not signed in")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Session expired, please sign in again")
    user = db.get(User, payload.get("sub"))
    if not user:
        raise HTTPException(status_code=401, detail="Account not found")
    return user


def user_json(user: User) -> dict:
    # Same field names the React app used with Supabase (id, email, user_metadata.name/picture).
    return {
        "id": user.id,
        "email": user.email,
        "user_metadata": {"name": user.name, "picture": user.picture},
        "tier": user.tier,
        "files_used": user.files_used,
    }
