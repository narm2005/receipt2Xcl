"""API tests with Google Vision and DeepSeek stubbed; Supabase tokens are signed locally. Run: cd backend && pytest -q"""
import io
import time
import json
import os
import sys
import tempfile

import pytest

_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.update(
    BACKEND_API_KEY="test-key",
    SUPABASE_URL="https://proj.supabase.co",
    SUPABASE_JWT_SECRET="test-secret-test-secret-test-secret",
    DEEPSEEK_API_KEY="x",
    GOOGLE_APPLICATION_CREDENTIALS_JSON=json.dumps({"type": "service_account"}),
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db}",
    FREE_FILE_LIMIT="2",
)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jwt  # noqa: E402
import auth  # noqa: E402
import main  # noqa: E402
import processing  # noqa: E402
import routes  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

LLM_CALLS = {"n": 0}


async def fake_parse(text):
    LLM_CALLS["n"] += 1
    return {"ReceiptInfo": {"merchant": "Big Bazaar", "receiptDate": "11/02/2026", "total": 450.5, "ITEMS": [
        {"description": "MLK", "unabbreviatedDescription": "Milk", "totalPrice": 50.5},
        {"description": "RICE 5KG", "unabbreviatedDescription": "Rice 5kg", "totalPrice": 400},
    ]}}


processing.extract_google_text = lambda content: "RECEIPT TEXT"
processing.parse_with_deepseek = fake_parse


ISSUER = "https://proj.supabase.co/auth/v1"
client = TestClient(main.app)


def supabase_token(who, key="test-secret-test-secret-test-secret", alg="HS256", **overrides):
    claims = {
        "sub": f"00000000-0000-0000-0000-{who.encode().hex()[:12].ljust(12, '0')}",
        "email": f"{who}@example.com",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
        "user_metadata": {"full_name": who.title(), "avatar_url": None},
        **overrides,
    }
    return jwt.encode(claims, key, algorithm=alg)


def sign_in(who="ann"):
    headers = {"Authorization": f"Bearer {supabase_token(who)}"}
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return headers, r.json()


def upload(headers, content=b"image-bytes", name="r.jpg"):
    return client.post("/receipts", headers=headers, files={"files": (name, io.BytesIO(content), "image/jpeg")})


def test_sign_in_and_me():
    headers, user = sign_in("ann")
    assert user["email"] == "ann@example.com" and user["tier"] == "freemium"
    assert client.get("/auth/me", headers=headers).json()["user_metadata"]["name"] == "Ann"
    assert client.get("/auth/me", headers=headers).json()["id"] == user["id"]  # same user on every request
    for bad in (
        supabase_token("ann", key="wrong-secret-wrong-secret-wrong-sec"),
        supabase_token("ann", aud="anon"),
        supabase_token("ann", iss="https://other.supabase.co/auth/v1"),
        supabase_token("ann", exp=int(time.time()) - 10),
    ):
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_upload_list_and_cache():
    headers, _ = sign_in("bob")
    before = LLM_CALLS["n"]
    r = upload(headers, b"bob-receipt-1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["receipts"][0]["merchant"] == "Big Bazaar"
    assert body["mergedData"]["combinedItems"][1]["description"] == "Rice 5kg"
    assert body["mergedData"]["summary"]["totalAmount"] == "450.50"
    upload(headers, b"bob-receipt-1")  # same image again: served from cache
    assert LLM_CALLS["n"] == before + 1
    listed = client.get("/receipts", headers=headers).json()
    assert len(listed["receipts"]) == 2 and listed["files_used"] == 2
    assert listed["receipts"][0]["processed_data"]["items"][0]["amount"] == 50.5


def test_free_quota_counts_every_file():
    headers, _ = sign_in("cat")
    assert upload(headers, b"c1").status_code == 200
    # One free file left: two at once is refused, with how many are left.
    two = [("files", ("a.jpg", io.BytesIO(b"x"), "image/jpeg")), ("files", ("b.jpg", io.BytesIO(b"y"), "image/jpeg"))]
    r = client.post("/receipts", headers=headers, files=two)
    assert r.status_code == 403 and "1 file left" in r.json()["detail"]
    assert upload(headers, b"c2").status_code == 200
    r = upload(headers, b"c3")
    assert r.status_code == 403 and "used all" in r.json()["detail"]


def test_free_user_can_upload_several_at_once():
    headers, _ = sign_in("cyd")
    two = [("files", ("a.jpg", io.BytesIO(b"cy-a"), "image/jpeg")), ("files", ("b.jpg", io.BytesIO(b"cy-b"), "image/jpeg"))]
    r = client.post("/receipts", headers=headers, files=two)
    assert r.status_code == 200 and len(r.json()["receipts"]) == 2
    assert client.get("/auth/me", headers=headers).json()["files_used"] == 2


def test_users_cannot_see_each_other():
    dan, _ = sign_in("dan")
    eve, _ = sign_in("eve")
    rid = upload(dan, b"dan-1").json()["receipts"][0]["fileId"]
    assert client.get(f"/receipts/{rid}", headers=eve).status_code == 404
    assert client.delete(f"/receipts/{rid}", headers=eve).status_code == 404
    assert client.get(f"/receipts/export?format=csv&ids={rid}", headers=eve).status_code == 404
    assert client.get("/receipts", headers=eve).json()["receipts"] == []
    assert client.delete(f"/receipts/{rid}", headers=dan).status_code == 200


def test_exports_and_premium_gates():
    headers, user = sign_in("fay")
    upload(headers, b"fay-1")
    csv_resp = client.get("/receipts/export?format=csv", headers=headers)
    assert csv_resp.status_code == 200 and "Rice 5kg" in csv_resp.text
    assert "attachment" in csv_resp.headers["content-disposition"]
    assert client.get("/receipts/export?format=xlsx", headers=headers).status_code == 403
    assert client.get("/analytics", headers=headers).status_code == 403

    from database import SessionLocal, User
    db = SessionLocal()
    db.get(User, user["id"]).tier = "premium"
    db.commit()
    db.close()

    xlsx = client.get("/receipts/export?format=xlsx", headers=headers)
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(xlsx.content)).active
    assert ws["F2"].value == "Milk" and ws["G3"].value == 400
    data = client.get("/analytics", headers=headers).json()["analytics"]
    assert data[0]["month_year"] == "2026-02" and data[0]["total_amount"] == 450.5


def test_rejects_wrong_type_and_failed_ocr():
    headers, _ = sign_in("gus")
    r = client.post("/receipts", headers=headers, files={"files": ("x.exe", io.BytesIO(b"MZ"), "application/x-msdownload")})
    assert r.status_code == 422

    def boom(content):
        raise RuntimeError("Vision API error: billing disabled")
    original = processing.extract_google_text
    processing.extract_google_text = boom
    try:
        r = upload(headers, b"never-seen-before")
        assert r.status_code == 422 and "billing" not in r.text  # internal reason stays in the server log
    finally:
        processing.extract_google_text = original


def test_legacy_process_endpoint_still_guarded():
    body = {"files": [{"file_id": "1", "file_name": "u/a.jpg", "user_id": "u", "content_base64": "aW1n"}]}
    assert client.post("/process", json=body).status_code == 401
    r = client.post("/process", json=body, headers={"X-API-Key": "test-key"})
    assert r.status_code == 200 and r.json()["files"][0]["merchant"] == "Big Bazaar"


def test_asymmetric_supabase_keys(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())

    class FakeJwks:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": private.public_key()})()

    monkeypatch.setattr(auth, "_jwks", FakeJwks())
    good = supabase_token("gil", key=private, alg="ES256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {good}"}).json()["email"] == "gil@example.com"
    forged = supabase_token("gil", key=ec.generate_private_key(ec.SECP256R1()), alg="ES256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def _make_premium(user_id):
    from database import SessionLocal, User
    db = SessionLocal()
    db.get(User, user_id).tier = "premium"
    db.commit()
    db.close()


def test_gst_fields_edit_and_monthly_export():
    headers, user = sign_in("hal")
    _make_premium(user["id"])
    rid = upload(headers, b"hal-1").json()["receipts"][0]["fileId"]
    r = client.patch(f"/receipts/{rid}", headers=headers, json={
        "merchant": "Hal Traders", "date": "05/10/2026", "total": 1050, "gstin": "33abcde1234f1z5",
        "invoiceNumber": "INV-9", "cgst": 25, "sgst": 25,
        "items": [{"description": "Cement bag", "amount": 1000, "category": "supplies"}],
    })
    assert r.status_code == 200, r.text
    d = r.json()["processed_data"]
    assert d["merchant"] == "Hal Traders" and d["gstin"] == "33ABCDE1234F1Z5" and d["items"][0]["amount"] == 1000
    assert r.json()["total"] == 1050 and r.json()["item_count"] == 1
    upload(headers, b"hal-2")  # dated 11/02/2026 (11 Feb) by the fake parser

    csv_text = client.get("/receipts/export?format=csv&month=2026-10", headers=headers).text
    assert "Cement bag" in csv_text and "INV-9" in csv_text and "Rice 5kg" not in csv_text
    assert client.get("/receipts/export?format=csv&month=2025-01", headers=headers).status_code == 404

    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(client.get("/receipts/export?format=xlsx", headers=headers).content))
    gst = wb["GST summary"]
    assert [c.value for c in gst[1]][:5] == ["Date", "Merchant", "GSTIN", "Invoice No", "Taxable Value"]
    assert gst["E2"].value == 1000 and gst["F2"].value == 25 and gst["A4"].value == "Total"

    eve, _ = sign_in("eve")
    assert client.patch(f"/receipts/{rid}", headers=eve, json={"merchant": "x"}).status_code == 404


def test_fair_use_limits(monkeypatch):
    headers, user = sign_in("ivy")
    _make_premium(user["id"])
    monkeypatch.setattr(routes, "DAILY_FILE_LIMIT", 2)
    assert upload(headers, b"ivy-1").status_code == 200
    rid = upload(headers, b"ivy-2").json()["receipts"][0]["fileId"]
    client.delete(f"/receipts/{rid}", headers=headers)  # deleting does not give the quota back
    r = upload(headers, b"ivy-3")
    assert r.status_code == 429 and "today" in r.json()["detail"]
    usage = client.get("/auth/me", headers=headers).json()["usage"]
    assert usage["day_used"] == 2 and usage["month_limit"] == 1000
    monkeypatch.setattr(routes, "DAILY_FILE_LIMIT", 100)
    monkeypatch.setattr(routes, "MONTHLY_FILE_LIMIT", 2)
    assert "month" in upload(headers, b"ivy-4").json()["detail"]


def test_delete_account():
    headers, user = sign_in("jon")
    upload(headers, b"jon-1")
    assert client.delete("/auth/me", headers=headers).json()["deleted"] is True
    from database import Receipt, SessionLocal
    db = SessionLocal()
    assert db.query(Receipt).filter(Receipt.user_id == user["id"]).count() == 0
    db.close()
    again = client.get("/auth/me", headers=headers).json()  # a fresh, empty account if they sign in again
    assert again["files_used"] == 0


def test_ca_contact_link_and_email(monkeypatch):
    import ca
    headers, user = sign_in("kim")
    _make_premium(user["id"])
    rid = upload(headers, b"kim-1").json()["receipts"][0]["fileId"]

    assert client.put("/settings/ca", headers=headers, json={"whatsapp": "12"}).status_code == 422
    assert client.put("/settings/ca", headers=headers, json={"email": "nope"}).status_code == 422
    saved = client.put("/settings/ca", headers=headers,
                       json={"name": "Ravi CA", "whatsapp": "098765 43210", "email": "ravi@ca.example"}).json()
    assert saved["whatsapp"] == "919876543210" and saved["email_enabled"] is False
    assert client.get("/settings/ca", headers=headers).json()["name"] == "Ravi CA"

    # WhatsApp: a private link that opens without signing in, only for these receipts
    link = client.post("/ca/link", headers=headers, json={"ids": [rid], "label": "Feb 2026"}).json()
    token = link["url"].rsplit("/", 1)[1]
    f = client.get(f"/s/{token}")
    assert f.status_code == 200 and f.content[:2] == b"PK" and "receipts-feb-2026.xlsx" in f.headers["content-disposition"]
    assert client.get("/s/not-a-real-token").status_code == 404
    eve, _ = sign_in("eve")
    assert client.post("/ca/link", headers=eve, json={"ids": [rid]}).status_code == 404

    from database import SessionLocal, ShareLink
    from datetime import datetime, timedelta, timezone
    db = SessionLocal()
    db.get(ShareLink, token).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    db.close()
    assert client.get(f"/s/{token}").status_code == 404

    # Email: off until configured, then sent with the file attached and a copy to the user
    assert client.post("/ca/email", headers=headers, json={"ids": [rid]}).status_code == 503
    monkeypatch.setenv("BREVO_API_KEY", "k")
    monkeypatch.setenv("MAIL_FROM_EMAIL", "bills@slickreceipts.example")
    sent = []
    monkeypatch.setattr(ca, "send_email", lambda payload: sent.append(payload))
    monkeypatch.setattr(ca, "CA_EMAILS_PER_DAY", 1)
    r = client.post("/ca/email", headers=headers, json={"ids": [rid], "label": "Feb 2026"})
    assert r.status_code == 200 and r.json()["sent_to"] == "ravi@ca.example"
    p = sent[0]
    assert p["to"][0]["email"] == "ravi@ca.example" and p["cc"][0]["email"] == "kim@example.com"
    assert p["attachment"][0]["name"] == "receipts-feb-2026.xlsx" and "Feb 2026" in p["subject"]
    assert client.post("/ca/email", headers=headers, json={"ids": [rid]}).status_code == 429


def test_feedback(monkeypatch):
    import ca
    import feedback as fbmod
    r = client.post("/feedback", json={"category": "idea", "rating": 5, "message": "Please add Tally export", "email": "visitor@example.com"})
    assert r.status_code == 200
    assert client.post("/feedback", json={"message": "hi there", "email": "bad"}).status_code == 422
    assert client.post("/feedback", json={"message": "x"}).status_code == 400  # too short
    headers, user = sign_in("lea")
    monkeypatch.setenv("BREVO_API_KEY", "k")
    monkeypatch.setenv("MAIL_FROM_EMAIL", "bills@slickreceipts.example")
    monkeypatch.setenv("FEEDBACK_TO_EMAIL", "support@slickreceipts.example")
    sent = []
    monkeypatch.setattr(ca, "send_email", lambda p: sent.append(p))
    assert client.post("/feedback", headers=headers, json={"category": "bug", "message": "Export button is slow"}).status_code == 200
    assert sent[0]["to"][0]["email"] == "support@slickreceipts.example" and sent[0]["replyTo"]["email"] == "lea@example.com"
    from database import Feedback, SessionLocal
    db = SessionLocal()
    row = db.query(Feedback).filter(Feedback.user_id == user["id"]).one()
    assert row.category == "bug" and row.email == "lea@example.com"
    db.close()
    monkeypatch.setattr(fbmod, "PER_IP_PER_HOUR", 1)
    assert client.post("/feedback", headers=headers, json={"message": "one more thing"}).status_code == 429
    client.delete("/auth/me", headers=headers)
    db = SessionLocal()
    assert db.query(Feedback).filter(Feedback.email == "lea@example.com").count() == 0
    db.close()


def test_admin_settings_and_users(monkeypatch):
    headers, user = sign_in("max")
    other, other_user = sign_in("ned")
    assert client.get("/config").json()["premium_monthly"] == 199
    assert client.put("/admin/config", headers=headers, json={"currency": "USD", "premium_monthly": 5, "premium_yearly": 50}).status_code == 403
    assert client.get("/auth/me", headers=headers).json()["is_admin"] is False

    monkeypatch.setenv("ADMIN_EMAILS", "someone@x.com, MAX@example.com")
    assert client.get("/auth/me", headers=headers).json()["is_admin"] is True
    assert client.put("/admin/config", headers=headers, json={"currency": "XYZ", "premium_monthly": 5, "premium_yearly": 50}).status_code == 422
    saved = client.put("/admin/config", headers=headers, json={"currency": "usd", "premium_monthly": 4.99, "premium_yearly": 49}).json()
    assert saved["currency"] == "USD" and saved["currency_symbol"] == "$"
    pub = client.get("/config").json()
    assert pub["premium_monthly"] == 4.99 and pub["premium_yearly"] == 49

    found = client.get("/admin/users?q=ned", headers=headers).json()
    assert [u["email"] for u in found["users"]] == ["ned@example.com"]
    r = client.patch(f"/admin/users/{other_user['id']}", headers=headers, json={"tier": "premium"})
    assert r.status_code == 200 and r.json()["tier"] == "premium"
    assert client.get("/auth/me", headers=other).json()["tier"] == "premium"
    assert client.patch(f"/admin/users/{user['id']}", headers=other, json={"tier": "premium"}).status_code == 403
    assert client.get("/admin/users", headers=other).status_code == 403
    # put the defaults back for other tests
    client.put("/admin/config", headers=headers, json={"currency": "INR", "premium_monthly": 199, "premium_yearly": 1999})
