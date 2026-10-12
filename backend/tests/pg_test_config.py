"""
EduDuty Test Suite — PostgreSQL Test Configuration and Gating Helper
File: backend/tests/pg_test_config.py

Provides unified, secure connection resolution and explicit gating for PostgreSQL
integration tests without storing hardcoded credentials or leaking secrets.
"""

import os
import re
import socket
import uuid
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url


def is_postgres_required() -> bool:
    """Return True if PostgreSQL integration tests are strictly required by the environment switch."""
    val = os.environ.get("EDUDUTY_REQUIRE_POSTGRES_TESTS", "").strip().lower()
    return val in ("1", "true", "yes")


def redact_url(url_str: str) -> str:
    """Safely mask password in a database URL for error messages and logs."""
    if not url_str:
        return "<EMPTY>"
    try:
        u = make_url(url_str)
        return str(u._replace(password="***"))
    except Exception:
        # Fallback regex masking if URL parsing fails
        return re.sub(r":([^/@:]+)@", ":***@", str(url_str))


def check_tcp_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if TCP port is open and reachable without disclosing secrets."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        res = sock.connect_ex((host, int(port)))
        return res == 0
    except Exception:
        return False
    finally:
        sock.close()


def _resolve_raw_admin_url() -> str | None:
    """
    Resolve admin PostgreSQL URL from environment variables.
    NO hardcoded fallback credentials permitted.
    """
    # 1. Dedicated test URL env var
    dedicated_url = os.environ.get("POSTGRES_TEST_DATABASE_URL")
    if dedicated_url:
        return dedicated_url

    # 2. General DATABASE_URL if configured
    primary_url = os.environ.get("DATABASE_URL")
    if primary_url:
        return primary_url

    # 3. Component environment variables (e.g., provided via test runner or CI secrets)
    pg_pass = os.environ.get("PG_TEST_PASSWORD") or os.environ.get("EDUDUTY_TEST_PG_PASSWORD")
    if pg_pass:
        user = os.environ.get("PG_TEST_USER") or os.environ.get("POSTGRES_USER", "postgres")
        host = os.environ.get("PG_TEST_HOST", "127.0.0.1")
        port = os.environ.get("PG_TEST_PORT", "5433")
        dbname = os.environ.get("PG_TEST_DB", "eduduty_test_db")
        return f"postgresql+pg8000://{user}:{pg_pass}@{host}:{port}/{dbname}"

    return None



def get_pg_admin_url() -> str:
    """
    Resolve PostgreSQL admin URL for integration tests.
    
    If EDUDUTY_REQUIRE_POSTGRES_TESTS=1:
        Fails the test suite immediately (pytest.fail) if configuration is missing,
        non-PostgreSQL, or unreachable.
    If switch is disabled / unset:
        Skips the test suite cleanly (pytest.skip).
    """
    require_pg = is_postgres_required()
    raw_url = _resolve_raw_admin_url()

    # 1. Missing configuration check
    if not raw_url:
        msg = (
            "PostgreSQL test configuration is missing. "
            "To enable PostgreSQL integration tests, set DATABASE_URL, "
            "POSTGRES_TEST_DATABASE_URL, or PG_TEST_PASSWORD."
        )
        if require_pg:
            pytest.fail(f"BLOCKED: EDUDUTY_REQUIRE_POSTGRES_TESTS=1 is set, but {msg}")
        else:
            pytest.skip(f"PostgreSQL integration test skipped: {msg}")

    # 2. Dialect validation (never allow SQLite to satisfy PostgreSQL tests)
    if not raw_url.startswith("postgresql"):
        msg = (
            f"Configured database URL dialect is not PostgreSQL ({redact_url(raw_url)}). "
            "SQLite databases cannot satisfy PostgreSQL integration tests."
        )
        if require_pg:
            pytest.fail(f"BLOCKED: EDUDUTY_REQUIRE_POSTGRES_TESTS=1 is set, but {msg}")
        else:
            pytest.skip(f"PostgreSQL integration test skipped: {msg}")

    # 3. Reachability check
    try:
        u = make_url(raw_url)
        host = u.host or "127.0.0.1"
        port = u.port or 5432
    except Exception:
        host, port = "127.0.0.1", 5433

    if not check_tcp_port(host, port):
        msg = f"PostgreSQL database on {host}:{port} is unreachable."
        if require_pg:
            pytest.fail(f"BLOCKED: EDUDUTY_REQUIRE_POSTGRES_TESTS=1 is set, but {msg}")
        else:
            pytest.skip(f"PostgreSQL integration test skipped: {msg}")

    # 4. Engine connection check and test signing key synchronization
    try:
        eng = create_engine(raw_url)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1;"))

            # Ensure isolated test signing secret is active for PostgreSQL integration runs
            test_sec = os.environ.get("EDUDUTY_RLS_HMAC_SECRET", "").strip()
            if not test_sec or test_sec == "eduduty_insecure_default_hmac_secret_for_dev_only_32b":
                test_sec = "eduduty_test_secure_isolated_hmac_key_64_bytes_entropy_for_tests!"
                os.environ["EDUDUTY_RLS_HMAC_SECRET"] = test_sec

            try:
                table_exists = conn.execute(text(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth_internal' AND table_name = 'context_signing_key';"
                )).scalar()
                if table_exists:
                    conn.execute(text("""
                        INSERT INTO auth_internal.context_signing_key (secret_key, active)
                        SELECT :sec, true
                        WHERE NOT EXISTS (
                            SELECT 1 FROM auth_internal.context_signing_key WHERE secret_key = :sec AND active = true
                        );
                    """), {"sec": test_sec})
                    conn.commit()
            except Exception:
                pass
    except Exception as e:
        msg = f"Connection to PostgreSQL failed on {host}:{port}: {type(e).__name__}"
        if require_pg:
            pytest.fail(f"BLOCKED: EDUDUTY_REQUIRE_POSTGRES_TESTS=1 is set, but {msg}")
        else:
            pytest.skip(f"PostgreSQL integration test skipped: {msg}")

    return raw_url


def get_pg_ai_reader_url(admin_url: str) -> str:
    """
    Provide connection URL for the unprivileged ai_reader role.
    Uses AI_READER_DATABASE_URL if provided, or rotates an ephemeral test password
    via admin connection.
    """
    env_reader_url = os.environ.get("AI_READER_DATABASE_URL")
    if env_reader_url and env_reader_url.startswith("postgresql"):
        return env_reader_url

    # Generate ephemeral test token for this test run
    ephemeral_token = uuid.uuid4().hex
    admin_eng = create_engine(admin_url)
    with admin_eng.connect() as conn:
        conn.execute(text(
            f"ALTER ROLE ai_reader WITH LOGIN PASSWORD '{ephemeral_token}';"
        ))
        conn.commit()

    u = make_url(admin_url)
    drivername = u.drivername or "postgresql+pg8000"
    host = u.host or "127.0.0.1"
    port = u.port or 5433
    database = u.database or "eduduty_test_db"
    return f"{drivername}://ai_reader:{ephemeral_token}@{host}:{port}/{database}"
