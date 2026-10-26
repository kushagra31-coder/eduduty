import os
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables are loaded immediately
env_file = Path(__file__).resolve().parent / ".env"
if env_file.exists():
    load_dotenv(env_file)
else:
    load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

DB_PATH = Path(__file__).resolve().parent / "eduduty.db"


def _resolve_database_url() -> str:
    """Pick a working database.

    1. DATABASE_URL env var wins if set (converting relative sqlite to absolute DB_PATH).
    2. Fall back to local SQLite file for zero setup and instant performance.
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        if env_url.startswith("sqlite:///") and (env_url.endswith("./eduduty.db") or env_url.endswith("eduduty.db")):
            return f"sqlite:///{DB_PATH.as_posix()}"
        return env_url

    # Default to sqlite file directly to avoid multi-second connection timeouts
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


def get_readonly_engine():
    url = _resolve_database_url()
    if url.startswith("sqlite"):
        ro_uri = f"file:{DB_PATH.as_posix()}?mode=ro&uri=true"
        return create_engine(f"sqlite:///{ro_uri}", connect_args={"uri": True, "check_same_thread": False})
    else:
        return create_engine(url, connect_args={"options": "-c role=ai_reader"})

_readonly_engine = None


def get_readonly_connection():
    global _readonly_engine
    if _readonly_engine is None:
        _readonly_engine = get_readonly_engine()
    conn = _readonly_engine.connect()
    if str(_readonly_engine.url).startswith("sqlite"):
        conn.execute(text("PRAGMA query_only=ON;"))
    return conn

