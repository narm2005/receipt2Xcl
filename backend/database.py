import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./local.db")
    # Neon/Render give "postgres://" or "postgresql://"; SQLAlchemy needs the psycopg driver named.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _database_url()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,  # Neon closes idle connections; reconnect transparently
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Models ---


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    google_sub = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(320), index=True, nullable=True)
    name = Column(String(200), nullable=True)
    picture = Column(Text, nullable=True)
    tier = Column(String(20), nullable=False, default="freemium")  # freemium | premium
    # Lifetime count of processed files; deleting receipts does not reset the free quota.
    files_used = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class Receipt(Base):
    __tablename__ = "receipts"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    original_file_name = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="completed")  # completed | failed
    merchant = Column(String(255), nullable=True)
    receipt_date = Column(String(40), nullable=True)  # as printed on the receipt
    total = Column(Float, nullable=True)
    item_count = Column(Integer, nullable=True)
    category = Column(String(100), nullable=True)
    data_json = Column(Text, nullable=True)  # structured receipt (merchant, date, total, items)
    created_at = Column(DateTime(timezone=True), index=True, nullable=False, default=_now)


class CachedResult(Base):
    __tablename__ = "cached_results"

    id = Column(Integer, primary_key=True, index=True)
    file_hash = Column(String(64), unique=True, index=True, nullable=False)
    json_data = Column(Text, nullable=False)


class UploadLog(Base):
    __tablename__ = "upload_logs"

    id = Column(Integer, primary_key=True, index=True)
    ip = Column(String(45), index=True, nullable=False)
    upload_date = Column(Date, index=True, nullable=False)


# Create tables if they do not exist yet (safe to run on every start).
Base.metadata.create_all(bind=engine)
