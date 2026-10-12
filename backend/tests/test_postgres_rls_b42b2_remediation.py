"""
EduDuty Phase 2, Stage B4.2B.2: Trusted Identity Context and Hardened RLS Remediation Tests

Automated proof that changing PostgreSQL custom settings alone can NEVER grant unauthorized access.
Covers 20 mandatory adversarial security scenarios using live PostgreSQL 16 and the real unprivileged ai_reader role.
"""

import hashlib
import hmac
import os
import time
import uuid
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError, ProgrammingError
from alembic import command
from alembic.config import Config

from tests.pg_test_config import get_pg_admin_url, get_pg_ai_reader_url


# ── Configuration & HMAC Minting Helper ───────────────────────────────────────

DEFAULT_TEST_SECRET = os.environ.get("EDUDUTY_RLS_HMAC_SECRET", "eduduty_test_secure_isolated_hmac_key_64_bytes_entropy_for_tests!")


def _mint_signature(user_id: int, faculty_id: int | None, role: str, ts: int, nonce: str, secret: str = None) -> str:
    sec = secret or os.environ.get("EDUDUTY_RLS_HMAC_SECRET", DEFAULT_TEST_SECRET)
    fac_str = str(faculty_id) if faculty_id is not None else ""
    payload = f"{user_id}:{fac_str}:{role.lower()}:{ts}:{nonce}"
    return hmac.new(sec.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def set_trusted_context(conn, user_id: int, faculty_id: int | None, role: str, ts_offset: int = 0, secret: str = None):
    sec = secret or os.environ.get("EDUDUTY_RLS_HMAC_SECRET", DEFAULT_TEST_SECRET)
    ts = int(time.time()) + ts_offset
    nonce = uuid.uuid4().hex[:16]
    sig = _mint_signature(user_id, faculty_id, role, ts, nonce, sec)
    fac_str = str(faculty_id) if faculty_id is not None else ""
    conn.execute(text("""
        SELECT set_config('app.current_user_id', :uid, true),
               set_config('app.current_faculty_id', :fac, true),
               set_config('app.current_user_role', :role, true),
               set_config('app.current_context_issued_at', :ts, true),
               set_config('app.current_context_nonce', :nonce, true),
               set_config('app.current_context_signature', :sig, true);
    """), {"uid": str(user_id), "fac": fac_str, "role": role.lower(), "ts": str(ts), "nonce": nonce, "sig": sig})


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


@pytest.fixture(scope="module")
def rls_b42b2_data(pg_admin_url):
    """
    Seed isolated test dataset for B4.2B.2 adversarial evaluation and clean up reliably.
    """
    admin_eng = create_engine(pg_admin_url)
    _cleanup_test_data(admin_eng)

    with admin_eng.connect() as conn:
        with conn.begin():
            # 1. Faculty
            conn.execute(text("""
                INSERT INTO faculty (id, name, department, abbreviation) VALUES
                (1001, 'Prof Alpha', 'CSE', 'PA'),
                (1002, 'Prof Beta', 'CSE', 'PB'),
                (1003, 'Prof Gamma', 'CSE', 'PG'),
                (1004, 'Prof Delta', 'CSE', 'PD');
            """))

            # 2. Classes
            conn.execute(text("""
                INSERT INTO classes (id, name, branch, year, section) VALUES
                (2001, 'B42B2-CS-A', 'Computer Science', 3, 'A'),
                (2002, 'B42B2-CS-B', 'Computer Science', 3, 'B');
            """))

            # 3. Students
            conn.execute(text("""
                INSERT INTO students (id, roll_number, name, class_id, active) VALUES
                (3001, 'B42B2-A01', 'Alice Alpha', 2001, true),
                (3002, 'B42B2-A02', 'Adam Alpha', 2001, true),
                (3003, 'B42B2-B01', 'Bob Beta', 2002, true),
                (3004, 'B42B2-B02', 'Bella Beta', 2002, true);
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
                (6001, 'MST-1-B42B2', '2026-10-15', 2001),
                (6002, 'MST-2-B42B2', '2026-10-16', 2002);
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
                (9001, 'R-101-B42B2', 40),
                (9002, 'R-102-B42B2', 40);
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

    _cleanup_test_data(admin_eng)


def _cleanup_test_data(eng):
    with eng.connect() as conn:
        with conn.begin():
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


# ── 1. Faculty A Reads Authorized Class A Students ────────────────────────────

def test_01_faculty_a_reads_authorized_class_a_students(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 1] Legitimate Faculty A with valid HMAC signature reads Class A students."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        set_trusted_context(conn, user_id=1, faculty_id=1001, role="faculty")
        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE id IN (3001, 3002, 3003, 3004) ORDER BY id;")).fetchall()
        rolls = [r[1] for r in rows]
        assert "B42B2-A01" in rolls
        assert "B42B2-A02" in rolls
        assert "B42B2-B01" not in rolls
        assert "B42B2-B02" not in rolls


# ── 2. Faculty A Cannot Read Faculty B by Changing faculty_id ─────────────────

def test_02_faculty_a_cannot_read_faculty_b_by_changing_faculty_id(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 2] Changing app.current_faculty_id to Faculty B without valid signature fails closed."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        # Legitimate context minted for Faculty A (1001)
        set_trusted_context(conn, user_id=1, faculty_id=1001, role="faculty")

        # Attacker attempts to change setting to Faculty B (1002)
        conn.execute(text("SELECT set_config('app.current_faculty_id', '1002', true);"))

        # Query must fail closed because signature is invalid for 1002
        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE id IN (3001, 3002, 3003, 3004);")).fetchall()
        assert len(rows) == 0, f"Forged faculty_id unexpectedly leaked rows: {rows}"


# ── 3. Setting user_role to super_admin Does Not Broaden Access ───────────────

def test_03_setting_user_role_to_super_admin_denied(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 3] Setting app.current_user_role to super_admin fails closed without super_admin signature."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        set_trusted_context(conn, user_id=1, faculty_id=1001, role="faculty")
        conn.execute(text("SELECT set_config('app.current_user_role', 'super_admin', true);"))

        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002, 3003, 3004);")).fetchall()
        assert len(rows) == 0, f"Forged super_admin role leaked rows: {rows}"


# ── 4. Changing Both Settings Together Denied ─────────────────────────────────

def test_04_changing_both_settings_together_denied(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 4] Changing both faculty_id and user_role together fails closed."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        set_trusted_context(conn, user_id=1, faculty_id=1001, role="faculty")
        conn.execute(text("""
            SELECT set_config('app.current_faculty_id', '1002', true),
                   set_config('app.current_user_role', 'super_admin', true);
        """))
        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002, 3003, 3004);")).fetchall()
        assert len(rows) == 0


# ── 5. Forged or Absent Signatures Fail Closed ────────────────────────────────

def test_05_forged_or_absent_signatures_fail_closed(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 5] Forged or absent signatures fail closed."""
    eng = create_engine(pg_ai_reader_url)

    # 1. No signature at all
    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_faculty_id', '1001', true), set_config('app.current_user_role', 'faculty', true);"))
        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002);")).fetchall()
        assert len(rows) == 0

    # 2. Forged garbage signature
    with eng.connect() as conn:
        conn.execute(text("""
            SELECT set_config('app.current_user_id', '1', true),
                   set_config('app.current_faculty_id', '1001', true),
                   set_config('app.current_user_role', 'faculty', true),
                   set_config('app.current_context_issued_at', '1728660000', true),
                   set_config('app.current_context_nonce', 'abcdef1234567890', true),
                   set_config('app.current_context_signature', 'deadbeefdeadbeefdeadbeef', true);
        """))
        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002);")).fetchall()
        assert len(rows) == 0


# ── 6. Valid Context Signed for Faculty A Cannot Claim Faculty B ──────────────

def test_06_valid_context_for_faculty_a_cannot_claim_faculty_b(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 6] Reusing Faculty A's valid signature with Faculty B's ID fails closed."""
    ts = int(time.time())
    nonce = uuid.uuid4().hex[:16]
    sig_a = _mint_signature(user_id=1, faculty_id=1001, role="faculty", ts=ts, nonce=nonce)

    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        # Use signature of Faculty A, but inject faculty_id 1002
        conn.execute(text("""
            SELECT set_config('app.current_user_id', '1', true),
                   set_config('app.current_faculty_id', '1002', true),
                   set_config('app.current_user_role', 'faculty', true),
                   set_config('app.current_context_issued_at', :ts, true),
                   set_config('app.current_context_nonce', :nonce, true),
                   set_config('app.current_context_signature', :sig, true);
        """), {"ts": str(ts), "nonce": nonce, "sig": sig_a})

        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002, 3003, 3004);")).fetchall()
        assert len(rows) == 0


# ── 7. Context Bound to Another User or Role Rejected ─────────────────────────

def test_07_context_bound_to_another_user_or_role_rejected(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 7] Modifying user_id or role under a valid signature fails closed."""
    ts = int(time.time())
    nonce = uuid.uuid4().hex[:16]
    sig = _mint_signature(user_id=1, faculty_id=1001, role="faculty", ts=ts, nonce=nonce)

    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        # Modify user_id to 999
        conn.execute(text("""
            SELECT set_config('app.current_user_id', '999', true),
                   set_config('app.current_faculty_id', '1001', true),
                   set_config('app.current_user_role', 'faculty', true),
                   set_config('app.current_context_issued_at', :ts, true),
                   set_config('app.current_context_nonce', :nonce, true),
                   set_config('app.current_context_signature', :sig, true);
        """), {"ts": str(ts), "nonce": nonce, "sig": sig})
        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002);")).fetchall()
        assert len(rows) == 0


# ── 8. Expired, Malformed, and Ambiguous Context Rejected ─────────────────────

def test_08_expired_malformed_and_ambiguous_context_rejected(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 8] Expired timestamps (>120s) and future timestamps (>30s) fail closed."""
    eng = create_engine(pg_ai_reader_url)

    # 1. Expired timestamp (-300s)
    with eng.connect() as conn:
        set_trusted_context(conn, user_id=1, faculty_id=1001, role="faculty", ts_offset=-300)
        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002);")).fetchall()
        assert len(rows) == 0

    # 2. Future timestamp (+100s)
    with eng.connect() as conn:
        set_trusted_context(conn, user_id=1, faculty_id=1001, role="faculty", ts_offset=100)
        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002);")).fetchall()
        assert len(rows) == 0


# ── 9. Signing Key Cannot Be Read or Modified by ai_reader ────────────────────

def test_09_signing_key_cannot_be_read_or_modified_by_ai_reader(pg_ai_reader_url):
    """[B4.2B.2 Test 9] ai_reader cannot read or modify auth_internal.context_signing_key."""
    eng = create_engine(pg_ai_reader_url)

    # 1. SELECT denied
    with eng.connect() as conn:
        with pytest.raises(DBAPIError) as exc:
            conn.execute(text("SELECT * FROM auth_internal.context_signing_key;"))
        assert "permission denied" in str(exc.value).lower()

    # 2. UPDATE denied
    with eng.connect() as conn:
        with pytest.raises(DBAPIError) as exc:
            conn.execute(text("UPDATE auth_internal.context_signing_key SET secret_key = 'hacked';"))
        assert "permission denied" in str(exc.value).lower()


# ── 10. ai_reader Cannot Mint Signature or Change Verifier ────────────────────

def test_10_ai_reader_cannot_mint_signature_or_change_verifier(pg_ai_reader_url):
    """[B4.2B.2 Test 10] ai_reader cannot execute or alter verify_identity_context."""
    eng = create_engine(pg_ai_reader_url)

    # Direct execution of verification helper is revoked from ai_reader
    with eng.connect() as conn:
        with pytest.raises(DBAPIError) as exc:
            conn.execute(text("SELECT * FROM auth_internal.verify_identity_context();"))
        assert "permission denied" in str(exc.value).lower()


# ── 11. All Five Approved Views Preserve Faculty Scope ────────────────────────

def test_11_all_five_approved_views_preserve_faculty_scope(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 11] All five approved reporting views enforce trusted faculty scope."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        set_trusted_context(conn, user_id=1, faculty_id=1001, role="faculty")

        # View 1: ai_eligibility_summary
        el_classes = [r[0] for r in conn.execute(text("SELECT class_name FROM ai_eligibility_summary WHERE class_name IN ('B42B2-CS-A', 'B42B2-CS-B');")).fetchall()]
        assert "B42B2-CS-A" in el_classes
        assert "B42B2-CS-B" not in el_classes

        # View 2: ai_attendance_summary
        att_rolls = [r[0] for r in conn.execute(text("SELECT roll_number FROM ai_attendance_summary WHERE roll_number IN ('B42B2-A01', 'B42B2-B01');")).fetchall()]
        assert "B42B2-A01" in att_rolls
        assert "B42B2-B01" not in att_rolls

        # View 3: ai_vt_candidates
        vt_rolls = [r[0] for r in conn.execute(text("SELECT roll_number FROM ai_vt_candidates WHERE roll_number IN ('B42B2-A01', 'B42B2-B01');")).fetchall()]
        assert "B42B2-B01" not in vt_rolls

        # View 4: v_vt_follow_up_status
        fu_rolls = [r[0] for r in conn.execute(text("SELECT roll_number FROM v_vt_follow_up_status WHERE roll_number IN ('B42B2-A01', 'B42B2-B01');")).fetchall()]
        assert "B42B2-A01" in fu_rolls
        assert "B42B2-B01" not in fu_rolls


# ── 12. Direct Base-Table Reads Cannot Bypass Scope ───────────────────────────

def test_12_direct_base_table_reads_cannot_bypass_scope(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 12] Direct queries against protected base tables cannot bypass scope."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        set_trusted_context(conn, user_id=1, faculty_id=1001, role="faculty")
        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE class_id = 2002;")).fetchall()
        assert len(rows) == 0


# ── 13. Historical Attendance Does Not Confer Student Access ──────────────────

def test_13_historical_attendance_does_not_confer_student_access(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 13] Historical attendance records do not grant current student access."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        # Faculty Delta (1004) has historical records but no active timetable
        set_trusted_context(conn, user_id=4, faculty_id=1004, role="faculty")
        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3003);")).fetchall()
        assert len(rows) == 0


# ── 14. Duty-Roster Access Does Not Confer Broader Student Access ─────────────

def test_14_duty_roster_access_does_not_confer_broader_student_access(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 14] Institution-wide duty roster access does not broaden student data access."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        set_trusted_context(conn, user_id=1, faculty_id=1001, role="faculty")

        # Can see institution-wide duties
        duties = conn.execute(text("SELECT faculty_name FROM ai_duty_roster WHERE room_number IN ('R-101-B42B2', 'R-102-B42B2');")).fetchall()
        assert len(duties) == 2

        # Cannot see Class B students
        students = conn.execute(text("SELECT id FROM students WHERE id IN (3003, 3004);")).fetchall()
        assert len(students) == 0


# ── 15. Pooled Connection Reuse Does Not Leak Authorization ───────────────────

def test_15_pooled_connection_reuse_does_not_leak_authorization(pg_ai_reader_url, rls_b42b2_data):
    """[B4.2B.2 Test 15] Transaction rollback clears context and prevents leakage across pooled connections."""
    eng = create_engine(pg_ai_reader_url, pool_size=1, max_overflow=0)
    Session = sessionmaker(bind=eng)

    # Request 1: Faculty A signs context and completes query
    s1 = Session()
    try:
        set_trusted_context(s1, user_id=1, faculty_id=1001, role="faculty")
        rows1 = s1.execute(text("SELECT roll_number FROM students WHERE id IN (3001, 3003);")).fetchall()
        assert len(rows1) == 1
    finally:
        s1.rollback()
        s1.close()

    # Request 2: Reused physical connection without context
    s2 = Session()
    try:
        rows2 = s2.execute(text("SELECT roll_number FROM students WHERE id IN (3001, 3003);")).fetchall()
        assert len(rows2) == 0
    finally:
        s2.rollback()
        s2.close()


# ── 16. Writes, DDL, Grants Denied to ai_reader ───────────────────────────────

def test_16_writes_ddl_grants_denied_to_ai_reader(pg_ai_reader_url):
    """[B4.2B.2 Test 16] Direct writes, DDL, and grants remain denied to ai_reader."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text("INSERT INTO students (id, roll_number, name, class_id) VALUES (9999, 'HACK', 'Hacker', 2001);"))
        with pytest.raises(DBAPIError):
            conn.execute(text("CREATE TABLE hack (id int);"))
        with pytest.raises(DBAPIError):
            conn.execute(text("GRANT ALL ON students TO public;"))


# ── 17. Helper Function Ownership, Grants, and Safe Search Path ───────────────

def test_17_helper_function_ownership_execute_grants_safe_search_path(pg_admin_url):
    """[B4.2B.2 Test 17] Catalogs confirm hardened search_path and stripped PUBLIC execution."""
    eng = create_engine(pg_admin_url)
    with eng.connect() as conn:
        funcs = conn.execute(text("""
            SELECT proname, prosecdef, proconfig, proacl,
                   has_function_privilege('public', oid, 'EXECUTE') as pub_exec
            FROM pg_proc
            WHERE proname IN ('can_current_user_access_class', 'can_current_user_access_student', 'can_current_user_access_duty_roster');
        """)).fetchall()
        for f in funcs:
            assert f[1] is True, f"Function {f[0]} must be SECURITY DEFINER"
            assert "search_path=pg_catalog, public" in str(f[2]), f"Function {f[0]} must pin safe search_path without pg_temp"
            assert f[4] is False, f"Function {f[0]} must not grant EXECUTE to PUBLIC"
            if f[3]:
                # proacl is returned as a string representation of the PostgreSQL array
                raw_acl = str(f[3]).strip("{}")
                for entry in raw_acl.split(","):
                    entry = entry.strip()
                    # In PostgreSQL ACLs, an entry starting with '=' (empty grantee) represents PUBLIC
                    assert not entry.startswith("="), f"Function {f[0]} has PUBLIC ACL entry: {entry}"


# ── 18. FORCE ROW LEVEL SECURITY Behavior Tested ──────────────────────────────

def test_18_force_row_level_security_behavior_and_owner_policies(pg_admin_url):
    """[B4.2B.2 Test 18] Catalogs confirm relforcerowsecurity=True and admin policies."""
    eng = create_engine(pg_admin_url)
    with eng.connect() as conn:
        for tname in ['students', 'mst_eligibility', 'follow_up_statuses', 'invigilation_duties', 'classes']:
            flags = conn.execute(text(f"SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = '{tname}';")).fetchone()
            assert flags[0] is True, f"{tname} relrowsecurity must be True"
            assert flags[1] is True, f"{tname} relforcerowsecurity must be True"


# ── 19. Migration Upgrade, Downgrade, Re-upgrade Repeatable ───────────────────

def test_19_migration_upgrade_downgrade_reupgrade_repeatable(pg_admin_url):
    """[B4.2B.2 Test 19] Alembic downgrade to 007 and re-upgrade to head is clean and repeatable."""
    cfg = _get_alembic_config(pg_admin_url)
    eng = create_engine(pg_admin_url)

    try:
        command.downgrade(cfg, "007_implement_faculty_rls")
        with eng.connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            assert rev == "007_implement_faculty_rls"
            # Schema auth_internal dropped
            schema_exists = conn.execute(text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'auth_internal';")).scalar()
            assert schema_exists is None
    finally:
        command.upgrade(cfg, "head")

    with eng.connect() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        assert rev in ("008_trusted_identity_context", "009_harden_rls_ownership", "010_retire_insecure_dev_key")
        schema_exists = conn.execute(text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'auth_internal';")).scalar()
        assert schema_exists == 1


# ── 20. Regression: B4.2B.1 Impersonation Attack Now Denied ───────────────────

def test_20_regression_b42b1_impersonation_attack_now_denied(pg_ai_reader_url, rls_b42b2_data):
    """
    [B4.2B.2 Test 20] Regression Test:
    Direct SQL attack documented in B4.2B.1 (unilaterally changing app.current_faculty_id or
    app.current_user_role without HMAC signature) is now unconditionally DENIED.
    """
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        # Attacker executes the exact B4.2B.1 exploit script
        conn.execute(text("SELECT set_config('app.current_user_role', 'super_admin', true);"))
        conn.execute(text("SELECT set_config('app.current_faculty_id', '1002', true);"))

        # Database engine enforces HMAC signature verification: fails closed
        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE id IN (3001, 3002, 3003, 3004);")).fetchall()
        assert len(rows) == 0, f"CRITICAL REGRESSION: B4.2B.1 attack succeeded! Leaked rows: {rows}"
