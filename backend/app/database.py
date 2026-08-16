"""
Database setup (SQLAlchemy + SQLite).
Swap SQLALCHEMY_DATABASE_URL for a Postgres URL when deploying to the cloud
(e.g. postgresql://user:pass@host/dbname) -- everything else stays the same.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DB_PATH = os.environ.get("TM_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "toastmasters.db"))
SQLALCHEMY_DATABASE_URL = os.environ.get("TM_DATABASE_URL", f"sqlite:///{DB_PATH}")

connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
# pool_pre_ping: test each pooled connection before using it and silently
# reconnect if it's gone stale. Needed for free-tier hosted Postgres (e.g.
# Neon), which closes idle connections server-side -- without this, requests
# intermittently fail with "psycopg2.OperationalError: SSL connection has
# been closed unexpectedly". Harmless no-op for SQLite.
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args, pool_pre_ping=True, pool_recycle=280)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
