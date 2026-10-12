"""
EduDuty Phase 2, Stage B4.2A: Dedicated AI Reader Role and Secure View Migration Tests

Validates:
1. Migration 006 upgrade and downgrade on PostgreSQL test database.
2. All five approved AI reporting views include WITH (security_invoker = true).
3. ai_duty_roster exposes faculty_id.
4. AI-reader role is unprivileged (NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOCREATEROLE).
5. AI-reader role cannot perform DDL, DML, or GRANT operations.
6. Approved view reads execute successfully under the AI-reader role.
7. Direct underlying student-table access is denied.
8. Missing production AI_READER_DATABASE_URL fails closed.
9. SQLite development fallback continues to operate cleanly.
10. Passwords and credentials remain masked across all representations and errors.
"""

import os
import socket
import uuid
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from alembic import command
from alembic.config import Config

import database


# ── PostgreSQL Test URLs & Fixtures ──────────────────────────────────────────

from tests.pg_test_config import get_pg_admin_url, get_pg_ai_reader_url


@pytest.fixture(scope="module")
def pg_admin_url():
    return get_pg_admin_url()


@pytest.fixture(scope="module")
def pg_ai_reader_url(pg_admin_url):
    return get_pg_ai_reader_url(pg_admin_url)


def _get_alembic_config(db_url):
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    cfg = Config(ini_path)
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    return cfg


# ── 1. Migration 006 Upgrade / Downgrade Validation ──────────────────────────

def test_migration_006_upgrade_and_downgrade(pg_admin_url):
    """[PostgreSQL Integration] Verify Alembic downgrade to 005 and re-upgrade to 006."""
    cfg = _get_alembic_config(pg_admin_url)
    eng = create_engine(pg_admin_url)

    try:
        # 1. Downgrade to 005
        command.downgrade(cfg, "005_ai_views_integrity")
        with eng.connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            assert rev == "005_ai_views_integrity"

            # Verify security_invoker is NOT present on revision 005 views
            relopt = conn.execute(text("SELECT reloptions FROM pg_class WHERE relname = 'ai_duty_roster';")).scalar()
            assert relopt is None or "security_invoker" not in str(relopt)

            # Verify faculty_id is NOT in ai_duty_roster on revision 005
            cols = [
                r[0] for r in conn.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'ai_duty_roster';"
                )).fetchall()
            ]
            assert "faculty_id" not in cols
    finally:
        # 2. Re-upgrade to 006 (head) ensures active database is never left downgraded
        command.upgrade(cfg, "head")

    with eng.connect() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        assert rev in ("006_secure_ai_views", "007_implement_faculty_rls", "008_trusted_identity_context", "009_harden_rls_ownership", "010_retire_insecure_dev_key")

        # Verify security_invoker is restored
        relopt = conn.execute(text("SELECT reloptions FROM pg_class WHERE relname = 'ai_duty_roster';")).scalar()
        assert "security_invoker=true" in str(relopt)


# ── 2. View Security Invoker Semantics Validation ────────────────────────────

def test_all_five_views_have_security_invoker(pg_admin_url):
    """[PostgreSQL Integration] Verify all 5 approved AI views have WITH (security_invoker = true)."""
    eng = create_engine(pg_admin_url)
    expected_views = [
        "ai_eligibility_summary",
        "ai_attendance_summary",
        "ai_vt_candidates",
        "ai_duty_roster",
        "v_vt_follow_up_status",
    ]
    with eng.connect() as conn:
        for vname in expected_views:
            reloptions = conn.execute(
                text("SELECT reloptions FROM pg_class WHERE relname = :vname;"),
                {"vname": vname},
            ).scalar()
            assert reloptions is not None, f"View {vname} has no reloptions"
            assert "security_invoker=true" in str(reloptions), (
                f"View {vname} missing security_invoker=true: {reloptions}"
            )


# ── 3. View Column Schema Validation (faculty_id) ────────────────────────────

def test_ai_duty_roster_exposes_faculty_id(pg_admin_url):
    """[PostgreSQL Integration] Verify ai_duty_roster projects f.id AS faculty_id."""
    eng = create_engine(pg_admin_url)
    with eng.connect() as conn:
        cols = {
            r[0]: r[1]
            for r in conn.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'ai_duty_roster';"
            )).fetchall()
        }
        assert "faculty_id" in cols, "faculty_id column missing from ai_duty_roster"
        assert cols["faculty_id"] == "integer"
        assert "faculty_name" in cols
        assert "duty_status" in cols
        assert "mst_label" in cols
        assert "exam_date" in cols
        assert "room_number" in cols


# ── 4. AI-Reader Role Privilege Specification ────────────────────────────────

def test_ai_reader_role_is_not_superuser_and_no_bypassrls(pg_admin_url):
    """[PostgreSQL Integration] Verify ai_reader is strictly unprivileged."""
    eng = create_engine(pg_admin_url)
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
            "FROM pg_roles WHERE rolname = 'ai_reader';"
        )).mappings().first()
        assert row is not None, "ai_reader role does not exist"
        assert row["rolsuper"] is False, "ai_reader must NOT be superuser"
        assert row["rolbypassrls"] is False, "ai_reader must NOT bypass RLS"
        assert row["rolcreaterole"] is False, "ai_reader must NOT create roles"
        assert row["rolcreatedb"] is False, "ai_reader must NOT create databases"


# ── 5. AI-Reader Prohibited Operations (DDL, DML, GRANT) ─────────────────────

def test_ai_reader_cannot_write_ddl_or_grant(pg_ai_reader_url):
    """[PostgreSQL Integration] Verify ai_reader cannot perform write, DDL, or GRANT operations in independent transactions."""
    eng = create_engine(pg_ai_reader_url)
    prohibited_statements = [
        "CREATE TABLE hack_tab (id int);",
        "INSERT INTO classes (name, branch, year) VALUES ('HACK', 'CSE', 1);",
        "UPDATE classes SET name = 'HACKED';",
        "DELETE FROM classes WHERE id = 1;",
        "ALTER TABLE classes ADD COLUMN hack_col int;",
        "DROP TABLE classes;",
        "CREATE ROLE attacker;",
        "ALTER ROLE postgres WITH SUPERUSER;",
    ]
    for stmt in prohibited_statements:
        with eng.connect() as conn:
            failed = False
            try:
                conn.execute(text(stmt))
            except Exception as e:
                failed = True
                err = str(e).lower()
                assert "permission denied" in err or "must be owner" in err, f"Unexpected error for {stmt}: {err}"
            assert failed, f"Statement unexpectedly succeeded: {stmt}"


# ── 6. Approved View Reads Succeed Under AI-Reader ───────────────────────────

def test_ai_reader_approved_view_reads_succeed(pg_ai_reader_url):
    """[PostgreSQL Integration] Verify ai_reader role can successfully read all 5 approved views."""
    eng = create_engine(pg_ai_reader_url)
    expected_views = [
        "ai_eligibility_summary",
        "ai_attendance_summary",
        "ai_vt_candidates",
        "ai_duty_roster",
        "v_vt_follow_up_status",
    ]
    with eng.connect() as conn:
        # Verify authenticated identity in live PostgreSQL session is actually ai_reader
        curr_user = conn.execute(text("SELECT current_user;")).scalar()
        assert curr_user == "ai_reader", f"Expected current_user to be ai_reader, got {curr_user}"

        for vname in expected_views:
            count = conn.execute(text(f"SELECT count(*) FROM {vname};")).scalar()
            assert count >= 0



# ── 7. Direct Student-Table Access Denied ─────────────────────────────────────

def test_ai_reader_direct_student_table_access_denied(pg_ai_reader_url):
    """[PostgreSQL Integration] Verify direct table-level SELECT * on base tables is denied."""
    eng = create_engine(pg_ai_reader_url)
    restricted_tables = ["students", "users", "audit_logs"]
    for tname in restricted_tables:
        with eng.connect() as conn:
            with pytest.raises(DBAPIError) as exc:
                conn.execute(text(f"SELECT * FROM {tname};"))
            assert "permission denied" in str(exc.value).lower(), (
                f"Direct access to table {tname} was unexpectedly allowed!"
            )


# ── 7b. Column-Level vs Row-Level Security Boundary Test ─────────────────────

def test_ai_reader_granted_columns_accessible_until_rls(pg_ai_reader_url):
    """
    [PostgreSQL Integration] Verify column-level access vs row-level security boundary.
    
    Under PostgreSQL 15+ security_invoker = true views, ai_reader was granted column-level
    SELECT on specific base columns (e.g. students.id, name, roll_number).
    
    EXPECTED BEHAVIOR (PRE-STAGE B4.2B):
    - Selecting granted columns directly IS ALLOWED at column level.
    - Selecting ungranted columns or SELECT * is DENIED at table level.
    - Row filtering is NOT active until Stage B4.2B implements Row-Level Security (RLS).
    """
    eng = create_engine(pg_ai_reader_url)
    # 1. Granted columns succeed at column level
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT id, roll_number, name FROM students LIMIT 1;")).fetchall()
        assert isinstance(rows, list)

    # 2. Table-wide projection fails
    with eng.connect() as conn:
        with pytest.raises(DBAPIError) as exc:
            conn.execute(text("SELECT * FROM students LIMIT 1;"))
        assert "permission denied" in str(exc.value).lower()



# ── 8. Production URL Missing Fails Closed ───────────────────────────────────

def test_missing_production_ai_reader_url_fails_closed(monkeypatch):
    """Verify system fails closed when AI_READER_DATABASE_URL is missing in production."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+pg8000://app_user:pass@127.0.0.1:5433/eduduty_prod")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("AI_READER_DATABASE_URL", raising=False)
    monkeypatch.delenv("AI_DATABASE_URL", raising=False)

    import importlib
    import database as db_mod

    with pytest.raises(RuntimeError) as exc_info:
        importlib.reload(db_mod)

    err_msg = str(exc_info.value)
    assert "CONFIGURATION ERROR: Dedicated AI_READER_DATABASE_URL is mandatory" in err_msg
    assert "strictly forbidden" in err_msg


# ── 9. SQLite Development Fallback Preserved ─────────────────────────────────

def test_sqlite_fallback_and_existing_tests_continue_to_work(monkeypatch):
    """Verify SQLite fallback works cleanly without requiring AI_READER_DATABASE_URL."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AI_READER_DATABASE_URL", raising=False)
    monkeypatch.delenv("AI_DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "development")

    import importlib
    import database as db_mod
    importlib.reload(db_mod)

    assert "sqlite" in db_mod.SQLALCHEMY_DATABASE_URL
    assert "sqlite" in db_mod.AI_READER_DATABASE_URL

    with db_mod.engine.connect() as c1:
        assert c1.execute(text("SELECT 1;")).scalar() == 1
    with db_mod.ai_reader_engine.connect() as c2:
        assert c2.execute(text("SELECT 2;")).scalar() == 2


# ── 10. Credential Masking in AI Reader Engine ───────────────────────────────

def test_no_password_leaks_in_ai_reader_engine():
    """Verify passwords in AI_READER_DATABASE_URL are masked in string representations."""
    secret = "TopSecretAiReaderPass999!"
    url = f"postgresql+pg8000://ai_reader:{secret}@127.0.0.1:5433/eduduty_test_db"
    ro_eng = create_engine(url, execution_options={"postgresql_readonly": True})

    assert secret not in str(ro_eng)
    assert secret not in repr(ro_eng)
    assert secret not in str(ro_eng.url)
    assert "***" in str(ro_eng.url)
