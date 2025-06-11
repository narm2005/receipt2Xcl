# create_tables.py

from sqlalchemy import create_engine
from database import Base  # This should include UploadLog, CachedResult
from database import engine  # Must match the DATABASE_URL you're using

# Run this ONCE to create all tables
print("Creating tables...")
Base.metadata.create_all(bind=engine)
print("✅ Tables created.")
