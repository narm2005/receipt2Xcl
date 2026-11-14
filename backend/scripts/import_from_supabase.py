"""One-time copy of users and processed receipts from the old Supabase database into the new one.

Usage (from the backend folder):
    SUPABASE_DB_URL='postgresql://postgres:<password>@db.<project>.supabase.co:5432/postgres' \
    DATABASE_URL='<new Neon connection string>' \
    JWT_SECRET=unused python scripts/import_from_supabase.py

Safe to run more than once: rows already imported are skipped.
Imported users are linked to their Google account the first time they sign in (matched by email).
"""
import json
import os
import sys

import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import Receipt, SessionLocal, User  # noqa: E402

src_url = os.environ["SUPABASE_DB_URL"]
db = SessionLocal()
users_added = receipts_added = 0

with psycopg.connect(src_url) as src:
    usage = dict(src.execute(
        "select user_id::text, coalesce(sum(file_count), 0)::int from public.upload_logs group by user_id"
    ).fetchall())

    profiles = src.execute(
        "select id::text, email, name, picture, coalesce(user_tier, 'freemium') from public.profiles"
    ).fetchall()
    for pid, email, name, picture, tier in profiles:
        if db.get(User, pid):
            continue
        db.add(User(id=pid, google_sub=f"import:{pid}", email=email, name=name, picture=picture,
                    tier=tier if tier in ("freemium", "premium") else "freemium",
                    files_used=usage.get(pid, 0)))
        users_added += 1
    db.commit()

    rows = src.execute(
        """select id::text, user_id::text, original_file_name, file_size, merchant, total, item_count,
                  category, processed_data, created_at
           from public.processed_files where status = 'completed'"""
    ).fetchall()
    for rid, uid, fname, size, merchant, total, count, category, data, created in rows:
        if db.get(Receipt, rid) or not db.get(User, uid):
            continue
        data = data if isinstance(data, dict) else json.loads(data or "{}")
        db.add(Receipt(id=rid, user_id=uid, original_file_name=fname, file_size=size, status="completed",
                       merchant=merchant, receipt_date=data.get("date"), total=float(total or 0),
                       item_count=count, category=category, data_json=json.dumps(data), created_at=created))
        receipts_added += 1
    db.commit()

print(f"Imported {users_added} users and {receipts_added} receipts.")
