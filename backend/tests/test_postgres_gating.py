"""
EduDuty Phase 2, Stage B4.2A.2: PostgreSQL Test Gating and Credential Hygiene Unit Tests
File: backend/tests/test_postgres_gating.py

Validates:
1. When EDUDUTY_REQUIRE_POSTGRES_TESTS=1, missing configuration fails the test suite.
2. When EDUDUTY_REQUIRE_POSTGRES_TESTS=0 (or unset), missing configuration skips cleanly.
3. When EDUDUTY_REQUIRE_POSTGRES_TESTS=1, non-PostgreSQL (e.g. SQLite) URLs fail the test suite.
4. When EDUDUTY_REQUIRE_POSTGRES_TESTS=1, unreachable databases fail the test suite.
5. When EDUDUTY_REQUIRE_POSTGRES_TESTS=0 (or unset), unreachable databases skip cleanly.
6. redact_url() masks passwords across all formats and never discloses plaintext secrets.
"""

import os
import pytest
from tests.pg_test_config import (
    is_postgres_required,
    redact_url,
    get_pg_admin_url,
    _resolve_raw_admin_url,
)


def test_is_postgres_required_switch_variants(monkeypatch):
    """Verify is_postgres_required() properly parses true/false states."""
    for truthy in ("1", "true", "yes", "TRUE", "Yes "):
        monkeypatch.setenv("EDUDUTY_REQUIRE_POSTGRES_TESTS", truthy)
        assert is_postgres_required() is True

    for falsy in ("0", "false", "no", "", "other"):
        monkeypatch.setenv("EDUDUTY_REQUIRE_POSTGRES_TESTS", falsy)
        assert is_postgres_required() is False

    monkeypatch.delenv("EDUDUTY_REQUIRE_POSTGRES_TESTS", raising=False)
    assert is_postgres_required() is False


def test_redact_url_masks_plaintext_secrets():
    """Verify redact_url masks passwords and never leaks credentials."""
    secret = "TopSecretPassword123!"
    url1 = f"postgresql+pg8000://myuser:{secret}@127.0.0.1:5433/eduduty_test_db"
    redacted1 = redact_url(url1)
    assert secret not in redacted1
    assert "***" in redacted1
    assert "myuser" in redacted1
    assert "eduduty_test_db" in redacted1

    url2 = f"postgresql://admin:{secret}@db.internal:5432/production"
    redacted2 = redact_url(url2)
    assert secret not in redacted2
    assert "***" in redacted2


def test_gating_missing_config_fails_when_required(monkeypatch):
    """When EDUDUTY_REQUIRE_POSTGRES_TESTS=1, missing config must fail pytest."""
    monkeypatch.setenv("EDUDUTY_REQUIRE_POSTGRES_TESTS", "1")
    monkeypatch.delenv("POSTGRES_TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_TEST_PASSWORD", raising=False)
    monkeypatch.delenv("EDUDUTY_TEST_PG_PASSWORD", raising=False)

    with pytest.raises(pytest.fail.Exception) as exc_info:
        get_pg_admin_url()

    err = str(exc_info.value)
    assert "BLOCKED: EDUDUTY_REQUIRE_POSTGRES_TESTS=1 is set" in err
    assert "PostgreSQL test configuration is missing" in err


def test_gating_missing_config_skips_when_not_required(monkeypatch):
    """When EDUDUTY_REQUIRE_POSTGRES_TESTS is unset, missing config must skip cleanly."""
    monkeypatch.delenv("EDUDUTY_REQUIRE_POSTGRES_TESTS", raising=False)
    monkeypatch.delenv("POSTGRES_TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_TEST_PASSWORD", raising=False)
    monkeypatch.delenv("EDUDUTY_TEST_PG_PASSWORD", raising=False)

    with pytest.raises(pytest.skip.Exception) as exc_info:
        get_pg_admin_url()

    err = str(exc_info.value)
    assert "PostgreSQL integration test skipped" in err


def test_gating_sqlite_url_rejected_when_required(monkeypatch):
    """When EDUDUTY_REQUIRE_POSTGRES_TESTS=1, an SQLite URL must NOT satisfy the test."""
    monkeypatch.setenv("EDUDUTY_REQUIRE_POSTGRES_TESTS", "1")
    monkeypatch.setenv("POSTGRES_TEST_DATABASE_URL", "sqlite:///test.db")

    with pytest.raises(pytest.fail.Exception) as exc_info:
        get_pg_admin_url()

    err = str(exc_info.value)
    assert "BLOCKED: EDUDUTY_REQUIRE_POSTGRES_TESTS=1 is set" in err
    assert "SQLite databases cannot satisfy PostgreSQL integration tests" in err


def test_gating_unreachable_db_fails_when_required(monkeypatch):
    """When EDUDUTY_REQUIRE_POSTGRES_TESTS=1, an unreachable port must fail."""
    monkeypatch.setenv("EDUDUTY_REQUIRE_POSTGRES_TESTS", "1")
    # Port 54999 is not open
    monkeypatch.setenv("POSTGRES_TEST_DATABASE_URL", "postgresql+pg8000://user:pass@127.0.0.1:54999/test_db")

    with pytest.raises(pytest.fail.Exception) as exc_info:
        get_pg_admin_url()

    err = str(exc_info.value)
    assert "BLOCKED: EDUDUTY_REQUIRE_POSTGRES_TESTS=1 is set" in err
    assert "unreachable" in err or "failed" in err
    assert "pass" not in err  # password not disclosed in error message


def test_gating_unreachable_db_skips_when_not_required(monkeypatch):
    """When EDUDUTY_REQUIRE_POSTGRES_TESTS is unset, an unreachable port must skip."""
    monkeypatch.delenv("EDUDUTY_REQUIRE_POSTGRES_TESTS", raising=False)
    monkeypatch.setenv("POSTGRES_TEST_DATABASE_URL", "postgresql+pg8000://user:pass@127.0.0.1:54999/test_db")

    with pytest.raises(pytest.skip.Exception) as exc_info:
        get_pg_admin_url()

    err = str(exc_info.value)
    assert "PostgreSQL integration test skipped" in err
    assert "pass" not in err  # password not disclosed in error message
