"""Sign-in: the website signs in with Google through Supabase Auth and sends us the Supabase access token.

We verify that token here and keep our own user row (same id as the Supabase user), so tiers and usage live
in the backend's tables. Supabase projects sign tokens either with the legacy shared JWT secret (HS256) or
with asymmetric keys published at <SUPABASE_URL>/auth/v1/.well-known/jwks.json; both are supported.
"""
import os
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import User, get_db

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET") or ""
if not SUPABASE_URL:
    raise RuntimeError("Environment variable SUPABASE_URL must be set")

ISSUER = f"{SUPABASE_URL}/auth/v1"
_jwks = jwt.PyJWKClient(f"{ISSUER}/.well-known/jwks.json", cache_keys=True)


def verify_supabase_token(token: str) -> dict:
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg == "HS256":
            if not SUPABASE_JWT_SECRET:
                raise jwt.InvalidTokenError("SUPABASE_JWT_SECRET is not set")
            key = SUPABASE_JWT_SECRET
        elif alg in ("ES256", "RS256"):
            key = _jwks.get_signing_key_from_jwt(token).key
        else:
            raise jwt.InvalidTokenError(f"unsupported alg {alg}")
        return jwt.decode(token, key, algorithms=[alg], audience="authenticated", issuer=ISSUER)
    except jwt.PyJWTError as e:
        print(f"Rejected sign-in token: {type(e).__name__}: {str(e)[:200]}", flush=True)
        raise HTTPException(status_code=401, detail="Session expired, please sign in again")


def get_current_user(
    authorization: Optional[str] = Header(None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not signed in")
    claims = verify_supabase_token(authorization.split(" ", 1)[1].strip())
    uid = claims.get("sub")
    if not uid:
        raise HTTPException(status_code=401, detail="Not signed in")

    meta = claims.get("user_metadata") or {}
    email = claims.get("email")
    name = meta.get("full_name") or meta.get("name")
    picture = meta.get("avatar_url") or meta.get("picture")

    user = db.get(User, uid)
    if not user:
        user = User(id=uid, google_sub=f"supabase:{uid}", email=email, name=name, picture=picture)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif (email, name, picture) != (user.email, user.name, user.picture):
        user.email, user.name, user.picture = email or user.email, name or user.name, picture or user.picture
        db.commit()
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
