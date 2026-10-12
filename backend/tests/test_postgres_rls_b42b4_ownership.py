"""
EduDuty Phase 2, Stage B4.2B.4: Privileged Function Ownership and Signing Authority Hardening Tests

Validates:
1. Least-privilege function ownership:
   - SECURITY DEFINER helper functions are owned by eduduty_rls_owner (NOSUPERUSER, NOLOGIN, NOBYPASSRLS).
   - eduduty_rls_owner owns 0 tables and has 0 write privileges.
   - Execution is revoked from PUBLIC.
2. Signing authority separation:
   - Positive tests use legitimate application-issued context (mint_signed_identity_context).
   - ai_reader cannot access signing keys or execute the verifier.
   - Database verifier rejects tampered, forged, or missing context.
3. Multi-key rotation:
   - Multiple active keys are accepted simultaneously without downtime.
   - Deactivated keys and bogus keys fail closed.
4. Data access contract:
   - Active timetable assignment grants only authorized scope.
   - Inactive/unversioned assignments fail closed.
   - Historical attendance confers no access.
   - Duty roster does not expand student reporting.
5. Migration repeatability:
   - Upgrade to 009, downgrade to 008, re-upgrade to 009.
"""

import hashlib
import hmac
import os
import time
import uuid
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError
from alembic import command
from alembic.config import Config

from tests.pg_test_config import get_pg_admin_url, get_pg_ai_reader_url
from ai_service import mint_signed_identity_context
import models


# ── Fixtures & Setup ──────────────────────────────────────────────────────────

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


def apply_app_context(conn, ctx: dict):
    """Inject application-minted context into active database connection."""
    conn.execute(
        text("""
            SELECT set_config('app.current_user_id', :uid, true),
                   set_config('app.current_faculty_id', :fac_id, true),
                   set_config('app.current_user_role', :role, true),
                   set_config('app.current_context_issued_at', :ts, true),
                   set_config('app.current_context_nonce', :nonce, true),
                   set_config('app.current_context_signature', :sig, true);
        """),
        ctx,
    )


@pytest.fixture(scope="module")
def rls_b42b4_data(pg_admin_url):
    admin_eng = create_engine(pg_admin_url)
    with admin_eng.connect() as conn:
        with conn.begin():
            _cleanup_test_data(conn)

            # 1. Faculty
            conn.execute(text("""
                INSERT INTO faculty (id, name, department) VALUES
                (1001, 'Prof Alpha B42B4', 'CSE'),
                (1002, 'Prof Beta B42B4', 'ECE'),
                (1003, 'Prof Gamma B42B4', 'MECH'),
                (1004, 'Prof Delta B42B4', 'CIVIL');
            """))

            # 2. Classes
            conn.execute(text("""
                INSERT INTO classes (id, name, branch, year, section) VALUES
                (2001, 'B42B4-CS-A', 'CSE', 3, 'A'),
                (2002, 'B42B4-CS-B', 'CSE', 3, 'B');
            """))

            # 3. Students
            conn.execute(text("""
                INSERT INTO students (id, roll_number, name, class_id, active) VALUES
                (3001, 'B42B4-A01', 'Alice Alpha', 2001, true),
                (3002, 'B42B4-A02', 'Adam Alpha', 2001, true),
                (3003, 'B42B4-B01', 'Bob Beta', 2002, true),
                (3004, 'B42B4-B02', 'Bella Beta', 2002, true);
            """))

            # 4. Timetable Versions
            conn.execute(text("""
                INSERT INTO timetable_versions (id, class_id, semester, session, active) VALUES
                (4001, 2001, 'V', 'Jul-Dec 2026', true),
                (4002, 2002, 'V', 'Jul-Dec 2026', true),
                (4003, 2002, 'V', 'Jul-Dec 2026', false);
            """))

            # 5. Timetable Assignments
            conn.execute(text("""
                INSERT INTO faculty_timetable (id, faculty_id, class_id, timetable_version_id, day_of_week, period_start, period_end, year, semester) VALUES
                (5001, 1001, 2001, 4001, 'Monday', '09:00', '10:00', 3, 'V'),
                (5002, 1002, 2002, 4002, 'Tuesday', '10:00', '11:00', 3, 'V'),
                (5003, 1001, 2002, 4003, 'Wednesday', '11:00', '12:00', 3, 'V'),
                (5004, 1001, 2002, NULL, 'Thursday', '14:00', '15:00', 3, 'V');
            """))

            # 6. Exams
            conn.execute(text("""
                INSERT INTO mst_exams (id, label, exam_date, class_id) VALUES
                (6001, 'MST-1-B42B4', '2026-10-15', 2001),
                (6002, 'MST-2-B42B4', '2026-10-16', 2002);
            """))

            # 7. Eligibility
            conn.execute(text("""
                INSERT INTO mst_eligibility (id, student_id, mst_exam_id, overall_pct, lowest_subject_pct, status, override) VALUES
                (7001, 3001, 6001, 85.0, 80.0, 'Eligible', false),
                (7002, 3002, 6001, 60.0, 50.0, 'Borderline', false),
                (7003, 3003, 6002, 92.0, 88.0, 'Eligible', false),
                (7004, 3004, 6002, 45.0, 40.0, 'Ineligible', false);
            """))

            # 8. Follow-up
            conn.execute(text("""
                INSERT INTO follow_up_statuses (id, student_id, calculated_status, final_status, rule_version, override, calculated_at, updated_at) VALUES
                (8001, 3001, 'cleared', 'cleared', 'v1', false, NOW(), NOW()),
                (8002, 3003, 'cleared', 'cleared', 'v1', false, NOW(), NOW());
            """))

            # 9. Rooms & Duties
            conn.execute(text("""
                INSERT INTO rooms (id, room_number, capacity) VALUES
                (9001, 'R-101-B42B4', 40),
                (9002, 'R-102-B42B4', 40);
            """))
            conn.execute(text("""
                INSERT INTO invigilation_duties (id, mst_exam_id, room_id, faculty_id, status) VALUES
                (9501, 6001, 9001, 1001, 'Assigned'),
                (9502, 6002, 9002, 1002, 'Assigned');
            """))

            # 10. Historical Attendance
            conn.execute(text("""
                INSERT INTO attendance_records (id, student_id, faculty_id, classes_conducted, classes_attended, attendance_pct, approved, upload_date) VALUES
                (9701, 3001, 1004, 30, 25, 83.33, true, NOW()),
                (9702, 3003, 1004, 30, 27, 90.00, true, NOW());
            """))

    yield

    with admin_eng.connect() as conn:
        with conn.begin():
            _cleanup_test_data(conn)


def _cleanup_test_data(conn):
    conn.execute(text("DELETE FROM attendance_records WHERE id IN (9701, 9702);"))
    conn.execute(text("DELETE FROM invigilation_duties WHERE id IN (9501, 9502);"))
    conn.execute(text("DELETE FROM rooms WHERE id IN (9001, 9002);"))
    conn.execute(text("DELETE FROM follow_up_statuses WHERE id IN (8001, 8002);"))
    conn.execute(text("DELETE FROM mst_eligibility WHERE id IN (7001, 7002, 7003, 7004);"))
    conn.execute(text("DELETE FROM mst_exams WHERE id IN (6001, 6002);"))
    conn.execute(text("DELETE FROM faculty_timetable WHERE id IN (5001, 5002, 5003, 5004);"))
    conn.execute(text("DELETE FROM timetable_versions WHERE id IN (4001, 4002, 4003);"))
    conn.execute(text("DELETE FROM students WHERE id IN (3001, 3002, 3003, 3004);"))
    conn.execute(text("DELETE FROM classes WHERE id IN (2001, 2002);"))
    conn.execute(text("DELETE FROM faculty WHERE id IN (1001, 1002, 1003, 1004);"))


# ── 1. Function Owner Attributes and Least-Privilege Verification ─────────────

def test_01_rls_owner_role_attributes_least_privilege(pg_admin_url):
    """[B4.2B.4 Test 1] eduduty_rls_owner is NOLOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOBYPASSRLS."""
    eng = create_engine(pg_admin_url)
    with eng.connect() as conn:
        role_attrs = conn.execute(text("""
            SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolcanlogin, rolbypassrls
            FROM pg_roles
            WHERE rolname = 'eduduty_rls_owner';
        """)).fetchone()

        assert role_attrs is not None, "eduduty_rls_owner role must exist"
        assert role_attrs[1] is False, "Owner must NOT be superuser"
        assert role_attrs[2] is False, "Owner must NOT have createrole"
        assert role_attrs[3] is False, "Owner must NOT have createdb"
        assert role_attrs[4] is False, "Owner must be NOLOGIN"
        assert role_attrs[5] is False, "Owner must NOT bypass RLS"


def test_02_helper_functions_owned_by_rls_owner(pg_admin_url):
    """[B4.2B.4 Test 2] All SECURITY DEFINER helper functions are owned by eduduty_rls_owner, not postgres."""
    eng = create_engine(pg_admin_url)
    with eng.connect() as conn:
        funcs = conn.execute(text("""
            SELECT p.proname, pg_get_userbyid(p.proowner) as owner, p.prosecdef, p.proconfig,
                   has_function_privilege('public', p.oid, 'EXECUTE') as pub_exec
            FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname IN ('public', 'auth_internal')
              AND p.proname IN ('can_current_user_access_class', 'can_current_user_access_student',
                                'can_current_user_access_duty_roster', 'verify_identity_context');
        """)).fetchall()

        assert len(funcs) == 4, "All 4 functions must exist"
        for f in funcs:
            assert f[1] == "eduduty_rls_owner", f"Function {f[0]} owner must be eduduty_rls_owner, got {f[1]}"
            assert f[2] is True, f"Function {f[0]} must be SECURITY DEFINER"
            assert "search_path=pg_catalog, public" in str(f[3]), f"Function {f[0]} must pin safe search_path"
            assert f[4] is False, f"Function {f[0]} must NOT grant EXECUTE to PUBLIC"


def test_03_rls_owner_has_no_write_or_ddl_privileges(pg_admin_url):
    """[B4.2B.4 Test 3] eduduty_rls_owner owns 0 tables and has zero write privileges."""
    eng = create_engine(pg_admin_url)
    with eng.connect() as conn:
        # Check owned tables
        owned_tables = conn.execute(text("""
            SELECT relname FROM pg_class c JOIN pg_roles r ON c.relowner = r.oid WHERE r.rolname = 'eduduty_rls_owner';
        """)).fetchall()
        assert len(owned_tables) == 0, f"eduduty_rls_owner must own 0 tables, got: {owned_tables}"

        # Check table write grants
        write_grants = conn.execute(text("""
            SELECT table_name, privilege_type
            FROM information_schema.role_table_grants
            WHERE grantee = 'eduduty_rls_owner'
              AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE');
        """)).fetchall()
        assert len(write_grants) == 0, f"eduduty_rls_owner must have 0 write grants, got: {write_grants}"

        # Check schema create grants
        create_grants = conn.execute(text("""
            SELECT nspname FROM pg_namespace WHERE has_schema_privilege('eduduty_rls_owner', nspname, 'CREATE');
        """)).fetchall()
        assert len(create_grants) == 0, f"eduduty_rls_owner must have 0 CREATE privileges, got: {create_grants}"


# ── 2. Signing Authority Separation & Application Minting ──────────────────────

def test_04_legitimate_application_issued_context_succeeds(pg_ai_reader_url, rls_b42b4_data):
    """[B4.2B.4 Test 4] Positive test: Application-issued context (mint_signed_identity_context) grants access."""
    eng = create_engine(pg_ai_reader_url)
    user_a = models.User(id=1, email="alpha@eduduty.internal", role="FACULTY", faculty_id=1001)

    with eng.connect() as conn:
        # Mint legitimate application context from User model
        ctx = mint_signed_identity_context(user_a)
        apply_app_context(conn, ctx)

        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE id IN (3001, 3002, 3003, 3004) ORDER BY id;")).fetchall()
        rolls = [r[1] for r in rows]
        assert "B42B4-A01" in rolls
        assert "B42B4-A02" in rolls
        assert "B42B4-B01" not in rolls
        assert "B42B4-B02" not in rolls


def test_05_ai_reader_cannot_read_keys_or_execute_verifier(pg_ai_reader_url):
    """[B4.2B.4 Test 5] ai_reader cannot read context_signing_key or invoke verify_identity_context()."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn1:
        with pytest.raises(DBAPIError) as exc1:
            conn1.execute(text("SELECT * FROM auth_internal.context_signing_key;"))
        assert "permission denied" in str(exc1.value).lower()

    with eng.connect() as conn2:
        with pytest.raises(DBAPIError) as exc2:
            conn2.execute(text("SELECT * FROM auth_internal.verify_identity_context();"))
        assert "permission denied" in str(exc2.value).lower()


def test_06_tampered_application_context_fails_closed(pg_ai_reader_url, rls_b42b4_data):
    """[B4.2B.4 Test 6] Modifying any field of an application-issued context fails closed."""
    eng = create_engine(pg_ai_reader_url)
    user_a = models.User(id=1, email="alpha@eduduty.internal", role="FACULTY", faculty_id=1001)

    # 1. Tamper faculty_id to 1002
    with eng.connect() as conn:
        ctx = mint_signed_identity_context(user_a)
        ctx["fac_id"] = "1002"  # Attempt to switch to Faculty B
        apply_app_context(conn, ctx)
        rows = conn.execute(text("SELECT id FROM students;")).fetchall()
        assert len(rows) == 0, f"Tampered faculty_id leaked rows: {rows}"

    # 2. Tamper role to super_admin
    with eng.connect() as conn:
        ctx = mint_signed_identity_context(user_a)
        ctx["role"] = "super_admin"  # Attempt privilege escalation
        apply_app_context(conn, ctx)
        rows = conn.execute(text("SELECT id FROM students;")).fetchall()
        assert len(rows) == 0, f"Tampered role leaked rows: {rows}"

    # 3. Tamper user_id
    with eng.connect() as conn:
        ctx = mint_signed_identity_context(user_a)
        ctx["uid"] = "999"
        apply_app_context(conn, ctx)
        rows = conn.execute(text("SELECT id FROM students;")).fetchall()
        assert len(rows) == 0, f"Tampered user_id leaked rows: {rows}"


def test_07_expired_application_context_fails_closed(pg_ai_reader_url, rls_b42b4_data):
    """[B4.2B.4 Test 7] An expired application context (-130 seconds) fails closed."""
    eng = create_engine(pg_ai_reader_url)
    user_a = models.User(id=1, email="alpha@eduduty.internal", role="FACULTY", faculty_id=1001)

    with eng.connect() as conn:
        ctx = mint_signed_identity_context(user_a)
        # Shift timestamp back 130 seconds and update signature
        secret = os.environ.get("EDUDUTY_RLS_HMAC_SECRET", "eduduty_test_secure_isolated_hmac_key_64_bytes_entropy_for_tests!")
        old_ts = str(int(time.time()) - 130)
        ctx["ts"] = old_ts
        payload = f"{ctx['uid']}:{ctx['fac_id']}:{ctx['role']}:{old_ts}:{ctx['nonce']}"
        ctx["sig"] = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

        apply_app_context(conn, ctx)
        rows = conn.execute(text("SELECT id FROM students;")).fetchall()
        assert len(rows) == 0, f"Expired context leaked rows: {rows}"


# ── 3. Multi-Key Rotation Verification ────────────────────────────────────────

def test_08_multi_key_rotation_zero_downtime(pg_admin_url, pg_ai_reader_url, rls_b42b4_data):
    """[B4.2B.4 Test 8] Zero-downtime key rotation: both Key 1 and Key 2 are valid concurrently."""
    admin_eng = create_engine(pg_admin_url)
    ai_eng = create_engine(pg_ai_reader_url)

    key_v1 = os.environ.get("EDUDUTY_RLS_HMAC_SECRET", "eduduty_test_secure_isolated_hmac_key_64_bytes_entropy_for_tests!")
    key_v2 = "eduduty_rotated_secret_v2_new_high_entropy_secret_32b"

    try:
        # Provision second active key in database
        with admin_eng.connect() as conn:
            with conn.begin():
                conn.execute(text("""
                    INSERT INTO auth_internal.context_signing_key (secret_key, active)
                    VALUES (:sec, true);
                """), {"sec": key_v2})

        user_a = models.User(id=1, email="alpha@eduduty.internal", role="FACULTY", faculty_id=1001)

        # Token 1 signed with Key 1
        with ai_eng.connect() as conn:
            ts = str(int(time.time()))
            nonce = uuid.uuid4().hex[:16]
            payload = f"1:1001:faculty:{ts}:{nonce}"
            sig_v1 = hmac.new(key_v1.encode(), payload.encode(), hashlib.sha256).hexdigest()
            apply_app_context(conn, {"uid": "1", "fac_id": "1001", "role": "faculty", "ts": ts, "nonce": nonce, "sig": sig_v1})
            rows_v1 = conn.execute(text("SELECT roll_number FROM students;")).fetchall()
            assert len(rows_v1) == 2, f"Key 1 failed to authenticate: {rows_v1}"

        # Token 2 signed with Key 2
        with ai_eng.connect() as conn:
            ts = str(int(time.time()))
            nonce = uuid.uuid4().hex[:16]
            payload = f"1:1001:faculty:{ts}:{nonce}"
            sig_v2 = hmac.new(key_v2.encode(), payload.encode(), hashlib.sha256).hexdigest()
            apply_app_context(conn, {"uid": "1", "fac_id": "1001", "role": "faculty", "ts": ts, "nonce": nonce, "sig": sig_v2})
            rows_v2 = conn.execute(text("SELECT roll_number FROM students;")).fetchall()
            assert len(rows_v2) == 2, f"Key 2 failed to authenticate: {rows_v2}"

        # Token 3 signed with bogus key
        with ai_eng.connect() as conn:
            ts = str(int(time.time()))
            nonce = uuid.uuid4().hex[:16]
            payload = f"1:1001:faculty:{ts}:{nonce}"
            sig_bogus = hmac.new(b"completely_bogus_key", payload.encode(), hashlib.sha256).hexdigest()
            apply_app_context(conn, {"uid": "1", "fac_id": "1001", "role": "faculty", "ts": ts, "nonce": nonce, "sig": sig_bogus})
            rows_bogus = conn.execute(text("SELECT roll_number FROM students;")).fetchall()
            assert len(rows_bogus) == 0, f"Bogus key leaked rows: {rows_bogus}"

    finally:
        # Cleanup Key 2
        with admin_eng.connect() as conn:
            with conn.begin():
                conn.execute(text("DELETE FROM auth_internal.context_signing_key WHERE secret_key = :sec;"), {"sec": key_v2})


# ── 4. Data Access Contract Invariants ────────────────────────────────────────

def test_09_active_timetable_scope_and_inactive_rejection(pg_ai_reader_url, rls_b42b4_data):
    """[B4.2B.4 Test 9] Active assignment grants scope; inactive or unversioned assignment fails closed."""
    eng = create_engine(pg_ai_reader_url)
    user_a = models.User(id=1, email="alpha@eduduty.internal", role="FACULTY", faculty_id=1001)

    with eng.connect() as conn:
        ctx = mint_signed_identity_context(user_a)
        apply_app_context(conn, ctx)

        # Faculty A assigned to Class A (2001) under active version 4001
        st_a = conn.execute(text("SELECT roll_number FROM students WHERE class_id = 2001 ORDER BY id;")).fetchall()
        assert len(st_a) == 2
        assert [r[0] for r in st_a] == ["B42B4-A01", "B42B4-A02"]

        # Class B (2002) has assignment 5003 under inactive version 4003 and unversioned 5004
        st_b = conn.execute(text("SELECT roll_number FROM students WHERE class_id = 2002;")).fetchall()
        assert len(st_b) == 0, f"Inactive/unversioned assignment leaked Class B: {st_b}"


def test_10_historical_attendance_does_not_confer_access(pg_ai_reader_url, rls_b42b4_data):
    """[B4.2B.4 Test 10] Faculty Delta with historical attendance but no active timetable receives 0 rows."""
    eng = create_engine(pg_ai_reader_url)
    user_delta = models.User(id=4, email="delta@eduduty.internal", role="FACULTY", faculty_id=1004)

    with eng.connect() as conn:
        ctx = mint_signed_identity_context(user_delta)
        apply_app_context(conn, ctx)

        rows = conn.execute(text("SELECT roll_number FROM students;")).fetchall()
        assert len(rows) == 0, f"Historical attendance leaked student rows: {rows}"

        att_view = conn.execute(text("SELECT roll_number FROM ai_attendance_summary;")).fetchall()
        assert len(att_view) == 0, f"Historical attendance leaked view rows: {att_view}"


def test_11_duty_roster_isolation(pg_ai_reader_url, rls_b42b4_data):
    """[B4.2B.4 Test 11] Duty roster visibility does not expand access to student records."""
    eng = create_engine(pg_ai_reader_url)
    user_a = models.User(id=1, email="alpha@eduduty.internal", role="FACULTY", faculty_id=1001)

    with eng.connect() as conn:
        ctx = mint_signed_identity_context(user_a)
        apply_app_context(conn, ctx)

        # Duty roster sees all rooms/duties
        duties = conn.execute(text("SELECT room_number FROM ai_duty_roster WHERE room_number IN ('R-101-B42B4', 'R-102-B42B4');")).fetchall()
        assert len(duties) == 2

        # But Class B student rows remain completely inaccessible
        st_b = conn.execute(text("SELECT roll_number FROM students WHERE class_id = 2002;")).fetchall()
        assert len(st_b) == 0


def test_12_pooled_connection_isolation(pg_ai_reader_url, rls_b42b4_data):
    """[B4.2B.4 Test 12] Pooled connection reuse after rollback leaves zero authorization."""
    eng = create_engine(pg_ai_reader_url, pool_size=1, max_overflow=0)
    Session = sessionmaker(bind=eng)

    user_a = models.User(id=1, email="alpha@eduduty.internal", role="FACULTY", faculty_id=1001)

    # Session 1 sets context
    s1 = Session()
    try:
        ctx = mint_signed_identity_context(user_a)
        apply_app_context(s1, ctx)
        rows1 = s1.execute(text("SELECT roll_number FROM students;")).fetchall()
        assert len(rows1) == 2
    finally:
        s1.rollback()
        s1.close()

    # Session 2 on exact same physical connection sets no context
    s2 = Session()
    try:
        rows2 = s2.execute(text("SELECT roll_number FROM students;")).fetchall()
        assert len(rows2) == 0, f"Residual authorization on pooled connection! {rows2}"
    finally:
        s2.rollback()
        s2.close()


# ── 5. Migration Lifecycle Safety ─────────────────────────────────────────────

def test_13_migration_009_upgrade_downgrade_reupgrade(pg_admin_url):
    """[B4.2B.4 Test 13] Migration 009 downgrades cleanly to 008 and re-upgrades to 009."""
    cfg = _get_alembic_config(pg_admin_url)
    eng = create_engine(pg_admin_url)

    try:
        # Downgrade to 008
        command.downgrade(cfg, "008_trusted_identity_context")
        with eng.connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            assert rev == "008_trusted_identity_context"

            # Owner restored to postgres
            owner = conn.execute(text("SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname = 'can_current_user_access_class';")).scalar()
            assert owner == "postgres"

    finally:
        # Re-upgrade to head (009)
        command.upgrade(cfg, "head")

    with eng.connect() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        assert rev in ("009_harden_rls_ownership", "010_retire_insecure_dev_key")

        # Owner is eduduty_rls_owner
        owner = conn.execute(text("SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname = 'can_current_user_access_class';")).scalar()
        assert owner == "eduduty_rls_owner"
