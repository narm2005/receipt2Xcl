from sqlalchemy import create_engine, Column, Integer, String, Date, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./test.db"  # For production, use PostgreSQL URL

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}  # Only for SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency for FastAPI

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Models

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

# Create tables if not exist
if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
