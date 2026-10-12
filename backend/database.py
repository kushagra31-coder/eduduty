import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

DB_PATH = Path(__file__).resolve().parent / "eduduty.db"


def _resolve_database_url() -> str:
    """Pick a working database.

    1. DATABASE_URL env var wins if set.
    2. Otherwise try local PostgreSQL (Supabase-local default port 54322).
    3. Fall back to a local SQLite file so the app boots with zero setup.
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    pg_url = "postgresql+psycopg://postgres:postgres@localhost:54322/postgres"
    try:
        import psycopg
        conn = psycopg.connect(
            "host=localhost port=54322 user=postgres password=postgres "
            "dbname=postgres connect_timeout=2"
        )
        conn.close()
        return pg_url
    except Exception as exc:
        print(f"database: PostgreSQL not reachable ({exc})", flush=True)
        return f"sqlite:///{DB_PATH.as_posix()}"


SQLALCHEMY_DATABASE_URL = _resolve_database_url()
print(f"database: using {SQLALCHEMY_DATABASE_URL}", flush=True)

connect_args = {}
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    # Needed for FastAPI's threaded request handling
    connect_args = {"check_same_thread": False}

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
