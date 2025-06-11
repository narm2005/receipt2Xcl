import hashlib
from google.cloud import firestore
from fastapi import HTTPException


db = firestore.Client()  # Firestore client


def generate_file_hash(content: bytes) -> str:
    """Generate SHA-256 hash of file content"""
    return hashlib.sha256(content).hexdigest()


async def get_cached_result(content: bytes) -> dict:
    """Check cache for existing OCR results"""
    file_hash = generate_file_hash(content)
    doc_ref = db.collection("receipt_cache").document(file_hash)
    doc = doc_ref.get()

    if doc.exists:
        # Update last accessed timestamp
        doc_ref.update({"last_accessed": firestore.SERVER_TIMESTAMP})
        return doc.to_dict()["ocr_result"]
    return None


async def cache_result(content: bytes, ocr_data: dict) -> None:
    """Store results in cache with TTL"""
    file_hash = generate_file_hash(content)
    doc_ref = db.collection("receipt_cache").document(file_hash)

    await doc_ref.set({
        "ocr_result": ocr_data,
        "created_at": firestore.SERVER_TIMESTAMP,
        "last_accessed": firestore.SERVER_TIMESTAMP,
        "hash": file_hash
    })