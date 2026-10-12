import os
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base


def _resolve_database_url() -> str:
    """Pick a working database.

    1. DATABASE_URL env var wins if set.
    2. Otherwise try local PostgreSQL (Supabase-local default port 54322).
    3. Fall back to a local SQLite file so the app boots with zero setup.
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        print(f"database: using DATABASE_URL from environment", flush=True)
        return env_url

    pg_url = "postgresql+psycopg://postgres:postgres@localhost:54322/postgres"
    try:
        import psycopg
        conn = psycopg.connect(
            "host=localhost port=54322 user=postgres password=postgres "
            "dbname=postgres connect_timeout=2"
        )
        conn.close()
        print("database: using PostgreSQL at localhost:54322", flush=True)
        return pg_url
    except Exception:
        print(
            "database: PostgreSQL not reachable; "
            "using local SQLite file eduduty.db",
            flush=True,
        )
        return "sqlite:///./eduduty.db"


SQLALCHEMY_DATABASE_URL = _resolve_database_url()

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


# ── AI Reader Database Engine & Session (SEC-04 Isolation) ───────────────────

def _resolve_ai_reader_database_url() -> str:
    """
    Pick a dedicated read-only database URL for AI read query execution.

    1. AI_READER_DATABASE_URL or AI_DATABASE_URL env var wins if set.
    2. In production PostgreSQL environments, a dedicated AI_READER_DATABASE_URL is mandatory.
       Fails closed with a RuntimeError if missing to prevent superuser privilege leakage.
    3. In local dev/test or SQLite environments, falls back with session-level read-only enforcement.
    """
    env_url = os.getenv("AI_READER_DATABASE_URL") or os.getenv("AI_DATABASE_URL")
    if env_url:
        print("database: using AI_READER_DATABASE_URL from environment", flush=True)
        return env_url

    # Check if primary database is PostgreSQL
    if SQLALCHEMY_DATABASE_URL.startswith("postgresql"):
        app_env = os.getenv("APP_ENV", "production").strip().lower()
        if app_env not in ("development", "dev", "test", "testing"):
            raise RuntimeError(
                "CONFIGURATION ERROR: Dedicated AI_READER_DATABASE_URL is mandatory for "
                "PostgreSQL operation in production. Falling back to primary application "
                "credentials is strictly forbidden."
            )
        print("database: warning: using primary database URL for AI reader in development/test", flush=True)

    return SQLALCHEMY_DATABASE_URL


AI_READER_DATABASE_URL = _resolve_ai_reader_database_url()

ai_reader_connect_args = {}
ai_reader_execution_options = {}

if AI_READER_DATABASE_URL.startswith("sqlite"):
    ai_reader_connect_args = {"check_same_thread": False}
elif AI_READER_DATABASE_URL.startswith("postgresql"):
    # Enforce PostgreSQL server-side read-only transactions across all PostgreSQL dialects (pg8000, psycopg2, etc.)
    ai_reader_execution_options = {"postgresql_readonly": True}
    # Pass options connect arg only for libpq-based drivers where supported (psycopg2/psycopg), never for pg8000
    if "+pg8000" not in AI_READER_DATABASE_URL and "pg8000" not in AI_READER_DATABASE_URL:
        ai_reader_connect_args = {"options": "-c default_transaction_read_only=on"}

ai_reader_engine = create_engine(
    AI_READER_DATABASE_URL,
    connect_args=ai_reader_connect_args,
    execution_options=ai_reader_execution_options,
)

# If SQLite is used (local dev/test), enforce PRAGMA query_only = ON at engine level
if AI_READER_DATABASE_URL.startswith("sqlite"):
    @event.listens_for(ai_reader_engine, "connect")
    def _set_sqlite_read_only(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA query_only = ON;")
        cursor.close()

AIReaderSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ai_reader_engine)


def get_ai_db():
    """
    FastAPI dependency for obtaining an isolated read-only AI reader database session.
    Routes all AI read operations exclusively through ai_reader_engine.
    """
    db = AIReaderSessionLocal()
    try:
        yield db
    finally:
        db.close()

