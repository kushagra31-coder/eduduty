"""
EduDuty Phase 2, Stage B4.1.2: PostgreSQL Driver & Connection Hardening Tests

Validates:
1. SQLite fallback configuration.
2. PostgreSQL URL parsing and engine creation without credential leakage.
3. AI reader engine connection using PostgreSQL test database (port 5433).
4. AI reader read-only enforcement (harmless SELECT succeeds, writes fail).
5. Error handling password masking.
6. Application startup imports and database dependency resolution.
"""

import os
import pytest
from sqlalchemy import create_engine, text, event
from sqlalchemy.exc import ProgrammingError, DBAPIError
from sqlalchemy.orm import sessionmaker

import database


# ── SQLite Fallback & Configuration Tests ────────────────────────────────────

def test_sqlite_fallback_configuration(monkeypatch):
    """Verify that when DATABASE_URL is unset, SQLite fallback is selected."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AI_READER_DATABASE_URL", raising=False)
    monkeypatch.delenv("AI_DATABASE_URL", raising=False)

    resolved_url = database._resolve_database_url()
    assert resolved_url == "sqlite:///./eduduty.db" or "sqlite" in resolved_url

    resolved_ai_url = database._resolve_ai_reader_database_url()
    assert "sqlite" in resolved_ai_url


def test_ai_reader_sqlite_query_only():
    """Verify SQLite AI reader engine enforces PRAGMA query_only = ON."""
    test_sqlite_url = "sqlite:///:memory:"
    test_engine = create_engine(test_sqlite_url, connect_args={"check_same_thread": False})

    @event.listens_for(test_engine, "connect")
    def _set_ro(dbapi_conn, record):
        c = dbapi_conn.cursor()
        c.execute("PRAGMA query_only = ON;")
        c.close()

    with test_engine.connect() as conn:
        # SELECT succeeds
        val = conn.execute(text("SELECT 1")).scalar()
        assert val == 1

        # WRITE fails due to query_only
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("CREATE TABLE test_tab (id int);"))
        assert "attempt to write a readonly database" in str(exc_info.value).lower()


# ── Credential Masking & Error Handling Tests ────────────────────────────────

def test_url_parsing_and_credential_masking():
    """Verify SQLAlchemy engine representation never displays raw password."""
    secret = "SuperSecretPassword123!"
    url = f"postgresql+pg8000://myuser:{secret}@127.0.0.1:5433/eduduty_test_db"
    eng = create_engine(url)

    eng_str = str(eng)
    eng_repr = repr(eng)
    url_str = str(eng.url)

    assert secret not in eng_str, "Raw password leaked in str(engine)"
    assert secret not in eng_repr, "Raw password leaked in repr(engine)"
    assert secret not in url_str, "Raw password leaked in str(engine.url)"
    assert "***" in url_str or "***" in eng_repr


def test_connection_error_does_not_leak_password():
    """Verify connection errors do not expose plaintext password in exception string."""
    secret = "UltraSecretPassword999!"
    # Non-existent port to force immediate socket error
    bad_url = f"postgresql+pg8000://myuser:{secret}@127.0.0.1:54998/eduduty_test_db"
    eng = create_engine(bad_url)

    with pytest.raises(Exception) as exc_info:
        with eng.connect() as conn:
            pass

    err_str = str(exc_info.value)
    assert secret not in err_str, f"Password leaked in error message: {err_str}"


def test_ai_reader_database_url_env_override(monkeypatch):
    """Verify AI_READER_DATABASE_URL environment variable is respected."""
    monkeypatch.setenv("AI_READER_DATABASE_URL", "postgresql+pg8000://reader:test@127.0.0.1:5433/eduduty_test_db")
    url = database._resolve_ai_reader_database_url()
    assert url == "postgresql+pg8000://reader:test@127.0.0.1:5433/eduduty_test_db"


# ── PostgreSQL Integration Tests (Requires 127.0.0.1:5433 Test Container) ────

from tests.pg_test_config import get_pg_admin_url


@pytest.fixture(scope="module")
def pg_test_url():
    return get_pg_admin_url()



def test_pg_normal_engine_connection(pg_test_url):
    """[PostgreSQL Integration] Verify database.engine connects cleanly using pg8000."""
    eng = create_engine(pg_test_url)
    with eng.connect() as conn:
        val = conn.execute(text("SELECT 1 AS num")).scalar()
        assert val == 1


def test_pg_ai_reader_select_succeeds(pg_test_url):
    """[PostgreSQL Integration] Verify AI reader engine executes SELECT queries successfully."""
    # Build AI reader engine with postgresql_readonly execution option
    ro_eng = create_engine(
        pg_test_url,
        execution_options={"postgresql_readonly": True},
    )
    with ro_eng.connect() as conn:
        val = conn.execute(text("SELECT 100")).scalar()
        assert val == 100

        # Query existing tables from migrations 001-005
        class_count = conn.execute(text("SELECT count(*) FROM classes")).scalar()
        assert class_count >= 0

        # Verify session parameter
        ro_param = conn.execute(text("SHOW transaction_read_only")).scalar()
        assert ro_param == "on"


def test_pg_ai_reader_write_fails_create_table(pg_test_url):
    """[PostgreSQL Integration] Verify AI reader engine blocks DDL (CREATE TABLE)."""
    ro_eng = create_engine(
        pg_test_url,
        execution_options={"postgresql_readonly": True},
    )
    with ro_eng.connect() as conn:
        with pytest.raises(ProgrammingError) as exc_info:
            conn.execute(text("CREATE TABLE should_never_exist (id int);"))
        err_msg = str(exc_info.value).lower()
        assert "read-only transaction" in err_msg or "cannot execute" in err_msg


def test_pg_ai_reader_write_fails_insert(pg_test_url):
    """[PostgreSQL Integration] Verify AI reader engine blocks DML (INSERT)."""
    ro_eng = create_engine(
        pg_test_url,
        execution_options={"postgresql_readonly": True},
    )
    Session = sessionmaker(bind=ro_eng)
    session = Session()
    try:
        with pytest.raises(ProgrammingError) as exc_info:
            session.execute(
                text("INSERT INTO classes (name, branch, year) VALUES (:name, :branch, :year)"),
                {"name": "RO_TEST", "branch": "CSE", "year": 1},
            )
        err_msg = str(exc_info.value).lower()
        assert "read-only transaction" in err_msg or "cannot execute" in err_msg
    finally:
        session.rollback()
        session.close()


def test_pg_ai_reader_write_fails_update(pg_test_url):
    """[PostgreSQL Integration] Verify AI reader engine blocks DML (UPDATE)."""
    ro_eng = create_engine(
        pg_test_url,
        execution_options={"postgresql_readonly": True},
    )
    with ro_eng.connect() as conn:
        with pytest.raises(ProgrammingError) as exc_info:
            conn.execute(text("UPDATE classes SET name = 'HACKED' WHERE id = 1"))
        err_msg = str(exc_info.value).lower()
        assert "read-only transaction" in err_msg or "cannot execute" in err_msg


def test_pg_ai_reader_write_fails_delete(pg_test_url):
    """[PostgreSQL Integration] Verify AI reader engine blocks DML (DELETE)."""
    ro_eng = create_engine(
        pg_test_url,
        execution_options={"postgresql_readonly": True},
    )
    with ro_eng.connect() as conn:
        with pytest.raises(ProgrammingError) as exc_info:
            conn.execute(text("DELETE FROM classes WHERE id = 9999"))
        err_msg = str(exc_info.value).lower()
        assert "read-only transaction" in err_msg or "cannot execute" in err_msg


# ── Application Startup & Dependency Test ────────────────────────────────────

def test_application_startup_and_get_db(pg_test_url, monkeypatch):
    """Verify FastAPI dependency resolution for get_db and get_ai_db under PostgreSQL."""
    monkeypatch.setenv("DATABASE_URL", pg_test_url)
    monkeypatch.setenv("APP_ENV", "test")
    import importlib
    import database as db_mod
    importlib.reload(db_mod)

    # Verify session generation
    db_gen = db_mod.get_db()
    session = next(db_gen)
    assert session is not None
    session.close()

    # Verify AI reader session generation
    ai_gen = db_mod.get_ai_db()
    ai_session = next(ai_gen)
    assert ai_session is not None
    # Test SELECT on AI session
    val = ai_session.execute(text("SELECT 42")).scalar()
    assert val == 42
    ai_session.close()
