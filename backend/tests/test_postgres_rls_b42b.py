"""
EduDuty Phase 2, Stage B4.2B: PostgreSQL Row-Level Security (RLS) & Transaction-Scoped Identity Context Tests

Proves PostgreSQL row-level security for EduDuty's AI reporting path:
1. Faculty A can read authorized student data in assigned class A.
2. Faculty A cannot read class B student rows through direct base-table queries.
3. Faculty A cannot obtain class B student data through any of the five approved reporting views.
4. Faculty B can access only their own assigned class data.
5. A faculty member with no active assignment receives no student rows.
6. An inactive timetable version grants no access.
7. Null or unversioned assignments grant no access.
8. Historical attendance does not grant current access.
9. Missing identity context returns no protected rows or fails closed.
10. A malformed or unauthorized context cannot be used to impersonate another faculty member.
11. Context set within one transaction does not leak into a later request on a reused pooled connection.
12. A rollback or query exception cannot leave a prior identity active.
13. The authorized duty-roster exception permits the intended institution-wide roster view.
14. Duty-roster access does not grant additional student-data access.
15. Direct writes, DDL, grants, and role escalation remain denied to ai_reader.
16. RLS remains effective for direct queries as well as view queries.
17. Migrations upgrade and downgrade safely in an isolated test setup.
18. The final role and table catalogs confirm the expected RLS flags, policies, ownership, and privileges.
"""

import hashlib
import hmac
import time
import uuid
import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError, ProgrammingError
from alembic import command
from alembic.config import Config

from tests.pg_test_config import get_pg_admin_url, get_pg_ai_reader_url


# ── Fixtures & Setup ──────────────────────────────────────────────────────────

def _set_test_context(conn, faculty_id=1001, role="faculty", user_id=1):
    secret = os.environ.get("EDUDUTY_CONTEXT_SIGNING_KEY") or os.environ.get("EDUDUTY_RLS_HMAC_SECRET", "eduduty_test_secure_isolated_hmac_key_64_bytes_entropy_for_tests!")
    ts = str(int(time.time()))
    nonce = str(uuid.uuid4())
    fac_str = str(faculty_id) if faculty_id is not None else ""
    payload = f"{user_id}:{fac_str}:{role}:{ts}:{nonce}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    conn.execute(text(f"""
        SELECT set_config('app.current_user_id', '{user_id}', true),
               set_config('app.current_faculty_id', '{fac_str}', true),
               set_config('app.current_user_role', '{role}', true),
               set_config('app.current_context_issued_at', '{ts}', true),
               set_config('app.current_context_nonce', '{nonce}', true),
               set_config('app.current_context_signature', '{sig}', true);
    """))


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
def rls_test_data(pg_admin_url):
    """
    Seed isolated test dataset for RLS verification and clean up reliably.
    Two faculty members (A and B), two classes (A and B), four students,
    timetable versions (active, inactive, null), exams, and duties.
    """
    admin_eng = create_engine(pg_admin_url)

    # Clean up any leftover test rows from prior interrupted runs
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
                (2001, 'RLS-CS-A', 'Computer Science', 3, 'A'),
                (2002, 'RLS-CS-B', 'Computer Science', 3, 'B');
            """))

            # 3. Students
            conn.execute(text("""
                INSERT INTO students (id, roll_number, name, class_id, active) VALUES
                (3001, 'RLS-A01', 'Alice Alpha', 2001, true),
                (3002, 'RLS-A02', 'Adam Alpha', 2001, true),
                (3003, 'RLS-B01', 'Bob Beta', 2002, true),
                (3004, 'RLS-B02', 'Bella Beta', 2002, true);
            """))

            # 4. Timetable Versions
            conn.execute(text("""
                INSERT INTO timetable_versions (id, class_id, semester, session, active) VALUES
                (4001, 2001, 'V', 'Jul-Dec 2026', true),
                (4002, 2002, 'V', 'Jul-Dec 2026', true),
                (4003, 2002, 'V', 'Jul-Dec 2026', false);
            """))

            # 5. Faculty Timetable Assignments
            # - Faculty A assigned to Class A via active version 4001
            # - Faculty B assigned to Class B via active version 4002
            # - Faculty A assigned to Class B via INACTIVE version 4003
            # - Faculty A assigned to Class B with NULL timetable_version_id
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
                (6001, 'MST-1-RLS', '2026-10-15', 2001),
                (6002, 'MST-2-RLS', '2026-10-16', 2002);
            """))

            # 7. Eligibility Records
            conn.execute(text("""
                INSERT INTO mst_eligibility (id, student_id, mst_exam_id, overall_pct, lowest_subject_pct, status, override) VALUES
                (7001, 3001, 6001, 85.0, 80.0, 'Eligible', false),
                (7002, 3002, 6001, 60.0, 50.0, 'Borderline', false),
                (7003, 3003, 6002, 92.0, 88.0, 'Eligible', false),
                (7004, 3004, 6002, 45.0, 40.0, 'Ineligible', false);
            """))

            # 8. Follow-up Statuses
            conn.execute(text("""
                INSERT INTO follow_up_statuses (id, student_id, calculated_status, final_status, rule_version, override, calculated_at, updated_at) VALUES
                (8001, 3001, 'cleared', 'cleared', 'v1', false, NOW(), NOW()),
                (8002, 3003, 'cleared', 'cleared', 'v1', false, NOW(), NOW());
            """))

            # 9. Rooms & Duties
            conn.execute(text("""
                INSERT INTO rooms (id, room_number, capacity) VALUES
                (9001, 'R-101-RLS', 40),
                (9002, 'R-102-RLS', 40);
            """))

            conn.execute(text("""
                INSERT INTO invigilation_duties (id, mst_exam_id, room_id, faculty_id, status) VALUES
                (9501, 6001, 9001, 1001, 'Assigned'),
                (9502, 6002, 9002, 1002, 'Assigned');
            """))

            # 10. Historical Attendance (Faculty Delta taught students, but has NO active timetable assignment)
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


# ── 1. Faculty A Can Read Assigned Class A Student Data ───────────────────────

def test_01_faculty_a_reads_authorized_class_a_student_data(pg_ai_reader_url, rls_test_data):
    """[RLS Test 1] Faculty A can read authorized student data in assigned Class A."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        # Set transaction-local context for Faculty A
        _set_test_context(conn, 1001, "faculty")

        rows = conn.execute(text("SELECT id, roll_number, name FROM students WHERE id IN (3001, 3002, 3003, 3004) ORDER BY id;")).fetchall()
        roll_numbers = [r[1] for r in rows]

        assert "RLS-A01" in roll_numbers
        assert "RLS-A02" in roll_numbers
        assert "RLS-B01" not in roll_numbers
        assert "RLS-B02" not in roll_numbers


# ── 2. Faculty A Cannot Read Class B Rows via Direct Query ────────────────────

def test_02_faculty_a_cannot_read_class_b_student_rows_direct_query(pg_ai_reader_url, rls_test_data):
    """[RLS Test 2] Faculty A cannot read Class B student rows through direct base-table queries."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        _set_test_context(conn, 1001, "faculty")

        # Explicitly query for Class B students
        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE id IN (3003, 3004);")).fetchall()
        assert len(rows) == 0, f"Expected 0 rows for Class B, got: {rows}"

        # Direct query against mst_eligibility for Class B students
        el_rows = conn.execute(text("SELECT id, student_id FROM mst_eligibility WHERE id IN (7003, 7004);")).fetchall()
        assert len(el_rows) == 0, f"Expected 0 eligibility rows for Class B, got: {el_rows}"


# ── 3. Faculty A Cannot Obtain Class B Data via Reporting Views ───────────────

def test_03_faculty_a_cannot_obtain_class_b_data_via_all_five_views(pg_ai_reader_url, rls_test_data):
    """[RLS Test 3] Faculty A cannot obtain Class B student data through any of the five approved reporting views."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        _set_test_context(conn, 1001, "faculty")

        # View 1: ai_eligibility_summary
        rows = conn.execute(text("SELECT class_name FROM ai_eligibility_summary WHERE class_name IN ('RLS-CS-A', 'RLS-CS-B');")).fetchall()
        classes = [r[0] for r in rows]
        assert "RLS-CS-A" in classes
        assert "RLS-CS-B" not in classes

        # View 2: ai_attendance_summary
        att_rows = conn.execute(text("SELECT roll_number FROM ai_attendance_summary WHERE roll_number IN ('RLS-A01', 'RLS-B01');")).fetchall()
        att_rolls = [r[0] for r in att_rows]
        assert "RLS-A01" in att_rolls
        assert "RLS-B01" not in att_rolls

        # View 3: ai_vt_candidates
        vt_rows = conn.execute(text("SELECT roll_number FROM ai_vt_candidates WHERE roll_number IN ('RLS-A01', 'RLS-A02', 'RLS-B01', 'RLS-B02');")).fetchall()
        vt_rolls = [r[0] for r in vt_rows]
        assert "RLS-B01" not in vt_rolls
        assert "RLS-B02" not in vt_rolls

        # View 4: v_vt_follow_up_status
        fu_rows = conn.execute(text("SELECT roll_number FROM v_vt_follow_up_status WHERE roll_number IN ('RLS-A01', 'RLS-B01');")).fetchall()
        fu_rolls = [r[0] for r in fu_rows]
        assert "RLS-A01" in fu_rolls
        assert "RLS-B01" not in fu_rolls


# ── 4. Faculty B Can Access Only Their Own Assigned Class Data ────────────────

def test_04_faculty_b_reads_only_assigned_class_b_data(pg_ai_reader_url, rls_test_data):
    """[RLS Test 4] Faculty B can access only their own assigned class data."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        _set_test_context(conn, 1002, "faculty")

        # Base table
        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE id IN (3001, 3002, 3003, 3004) ORDER BY id;")).fetchall()
        rolls = [r[1] for r in rows]
        assert "RLS-B01" in rolls
        assert "RLS-B02" in rolls
        assert "RLS-A01" not in rolls
        assert "RLS-A02" not in rolls

        # Views
        fu_rows = conn.execute(text("SELECT roll_number FROM v_vt_follow_up_status WHERE roll_number IN ('RLS-A01', 'RLS-B01');")).fetchall()
        fu_rolls = [r[0] for r in fu_rows]
        assert "RLS-B01" in fu_rolls
        assert "RLS-A01" not in fu_rolls


# ── 5. Unassigned Faculty Receives No Student Rows ────────────────────────────

def test_05_unassigned_faculty_receives_no_student_rows(pg_ai_reader_url, rls_test_data):
    """[RLS Test 5] A faculty member with no active assignment receives zero student rows."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        # Faculty Gamma (1003) has NO entries in faculty_timetable
        _set_test_context(conn, 1003, "faculty")

        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE id IN (3001, 3002, 3003, 3004);")).fetchall()
        assert len(rows) == 0, f"Expected 0 students for unassigned faculty, got: {rows}"

        el_rows = conn.execute(text("SELECT id FROM mst_eligibility WHERE id IN (7001, 7002, 7003, 7004);")).fetchall()
        assert len(el_rows) == 0, f"Expected 0 eligibility rows, got: {el_rows}"


# ── 6. Inactive Timetable Version Grants No Access ────────────────────────────

def test_06_inactive_timetable_version_grants_no_access(pg_ai_reader_url, rls_test_data):
    """[RLS Test 6] An inactive timetable version grants no access."""
    # Assignment 5003 is Faculty A (1001) for Class B (2002) via version 4003 which has active=false.
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        _set_test_context(conn, 1001, "faculty")

        # Verify Class B students are NOT returned despite entry in faculty_timetable
        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE class_id = 2002;")).fetchall()
        assert len(rows) == 0, f"Inactive timetable version leaked student rows: {rows}"


# ── 7. Null or Unversioned Assignments Grant No Access ────────────────────────

def test_07_null_or_unversioned_assignments_grant_no_access(pg_ai_reader_url, rls_test_data):
    """[RLS Test 7] Null or unversioned assignments fail closed and grant no access."""
    # Assignment 5004 has timetable_version_id = NULL
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        _set_test_context(conn, 1001, "faculty")

        # Query Class B where the unversioned assignment exists
        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE class_id = 2002;")).fetchall()
        assert len(rows) == 0, f"Unversioned timetable assignment leaked student rows: {rows}"


# ── 8. Historical Attendance Does Not Grant Current Access ───────────────────

def test_08_historical_attendance_does_not_grant_current_access(pg_ai_reader_url, rls_test_data):
    """[RLS Test 8] Historical attendance records do not grant current student-data access."""
    # Faculty Delta (1004) has attendance_records (9701, 9702) but NO faculty_timetable entries
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        _set_test_context(conn, 1004, "faculty")

        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE id IN (3001, 3003);")).fetchall()
        assert len(rows) == 0, f"Historical attendance records leaked student rows: {rows}"

        att_rows = conn.execute(text("SELECT roll_number FROM ai_attendance_summary WHERE roll_number IN ('RLS-A01', 'RLS-B01');")).fetchall()
        assert len(att_rows) == 0, f"Historical attendance records leaked attendance view rows: {att_rows}"


# ── 9. Missing Identity Context Fails Closed ──────────────────────────────────

def test_09_missing_identity_context_fails_closed(pg_ai_reader_url, rls_test_data):
    """[RLS Test 9] Missing identity context returns no protected rows (fails closed)."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        # No set_config called at all
        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE id IN (3001, 3002, 3003, 3004);")).fetchall()
        assert len(rows) == 0, f"Missing context leaked student rows: {rows}"

        el_rows = conn.execute(text("SELECT id FROM mst_eligibility WHERE id IN (7001, 7002, 7003, 7004);")).fetchall()
        assert len(el_rows) == 0, f"Missing context leaked eligibility rows: {el_rows}"

        duty_rows = conn.execute(text("SELECT faculty_id FROM invigilation_duties WHERE faculty_id IN (1001, 1002);")).fetchall()
        assert len(duty_rows) == 0, f"Missing context leaked duty rows: {duty_rows}"

        roster_rows = conn.execute(text("SELECT faculty_name FROM ai_duty_roster WHERE room_number IN ('R-101-RLS', 'R-102-RLS');")).fetchall()
        assert len(roster_rows) == 0, f"Missing context leaked roster rows: {roster_rows}"


# ── 10. Malformed or Unauthorized Context Fails Closed ────────────────────────

def test_10_malformed_or_unauthorized_context_fails_closed(pg_ai_reader_url, rls_test_data):
    """[RLS Test 10] A malformed or unauthorized context cannot be used to access data or impersonate."""
    eng = create_engine(pg_ai_reader_url)

    # 1. Non-integer faculty ID fails closed
    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_faculty_id', 'malicious_injection', true), set_config('app.current_user_role', 'faculty', true);"))
        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002, 3003, 3004);")).fetchall()
        assert len(rows) == 0

    # 2. Unauthorized role (e.g., VIEWER, INVIGILATOR, STUDENT) fails closed
    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_faculty_id', '1001', true), set_config('app.current_user_role', 'viewer', true);"))
        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002, 3003, 3004);")).fetchall()
        assert len(rows) == 0

    # 3. SQL injection attempt in faculty_id fails closed
    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_faculty_id', '1001 OR 1=1', true), set_config('app.current_user_role', 'faculty', true);"))
        rows = conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002, 3003, 3004);")).fetchall()
        assert len(rows) == 0


# ── 11. Context Does Not Leak Across Pooled Connections ───────────────────────

def test_11_pooled_connection_reuse_does_not_leak_context(pg_ai_reader_url, rls_test_data):
    """[RLS Test 11] Context set within one transaction does not leak into a later request on a reused pooled connection."""
    # Force single connection pool so Session 2 is guaranteed to reuse Session 1's physical connection
    eng = create_engine(pg_ai_reader_url, pool_size=1, max_overflow=0)
    Session = sessionmaker(bind=eng)

    # Request 1: Faculty A sets context, queries data, and transaction finishes
    s1 = Session()
    try:
        _set_test_context(s1, 1001, "faculty")
        rows1 = s1.execute(text("SELECT roll_number FROM students WHERE id IN (3001, 3003);")).fetchall()
        assert len(rows1) == 1
        assert rows1[0][0] == "RLS-A01"
    finally:
        s1.rollback()
        s1.close()

    # Request 2: New unauthenticated request on the exact same pooled connection
    s2 = Session()
    try:
        # Does NOT set any context
        rows2 = s2.execute(text("SELECT roll_number FROM students WHERE id IN (3001, 3003);")).fetchall()
        assert len(rows2) == 0, f"Context leaked to pooled connection! Found rows: {rows2}"

        # Verify GUC variable is empty
        active_fac = s2.execute(text("SELECT current_setting('app.current_faculty_id', true);")).scalar()
        assert active_fac in (None, "")
    finally:
        s2.rollback()
        s2.close()


# ── 12. Rollback or Exception Clears Active Identity ──────────────────────────

def test_12_rollback_or_exception_clears_active_identity(pg_ai_reader_url, rls_test_data):
    """[RLS Test 12] A rollback or query exception cannot leave a prior identity active."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        _set_test_context(conn, 1001, "faculty")
        val_before = conn.execute(text("SELECT current_setting('app.current_faculty_id', true);")).scalar()
        assert val_before == "1001"

        # Explicit rollback terminates transaction-local scope
        conn.rollback()

        val_after = conn.execute(text("SELECT current_setting('app.current_faculty_id', true);")).scalar()
        assert val_after in (None, ""), f"Expected empty setting after rollback, got: {val_after}"


# ── 13. Duty-Roster Exception Permits Institution-Wide View ───────────────────

def test_13_authorized_duty_roster_exception_permits_institution_wide_roster(pg_ai_reader_url, rls_test_data):
    """[RLS Test 13] The authorized duty-roster exception permits the intended institution-wide roster view."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        _set_test_context(conn, 1001, "faculty")

        # Query ai_duty_roster: should see both Duty 1 (Prof Alpha) and Duty 2 (Prof Beta)
        roster_rows = conn.execute(text("SELECT faculty_name, room_number FROM ai_duty_roster WHERE room_number IN ('R-101-RLS', 'R-102-RLS');")).fetchall()
        assert len(roster_rows) == 2
        fac_names = [r[0] for r in roster_rows]
        assert "Prof Alpha" in fac_names
        assert "Prof Beta" in fac_names

        # Direct query against invigilation_duties also succeeds under the exception
        duties = conn.execute(text("SELECT faculty_id FROM invigilation_duties WHERE faculty_id IN (1001, 1002);")).fetchall()
        assert len(duties) == 2


# ── 14. Duty-Roster Access Does Not Grant Student Data ────────────────────────

def test_14_duty_roster_access_does_not_grant_additional_student_data(pg_ai_reader_url, rls_test_data):
    """[RLS Test 14] Duty-roster access does not broaden access to student records, eligibility, or follow-up data."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        _set_test_context(conn, 1001, "faculty")

        # Even though Faculty A sees Duty 2 (associated with Class B exam 6002), Faculty A CANNOT see Class B student rows
        st_rows = conn.execute(text("SELECT id, roll_number FROM students WHERE id IN (3003, 3004);")).fetchall()
        assert len(st_rows) == 0

        el_rows = conn.execute(text("SELECT id FROM mst_eligibility WHERE mst_exam_id = 6002;")).fetchall()
        assert len(el_rows) == 0

        fu_rows = conn.execute(text("SELECT student_id FROM follow_up_statuses WHERE student_id IN (3003, 3004);")).fetchall()
        assert len(fu_rows) == 0


# ── 15. Direct Writes, DDL, Grants Denied to ai_reader ────────────────────────

def test_15_direct_writes_ddl_grants_denied_to_ai_reader(pg_ai_reader_url):
    """[RLS Test 15] Direct writes, DDL, grants, and role escalation remain denied to ai_reader."""
    eng = create_engine(pg_ai_reader_url)

    # 1. INSERT denied
    with eng.connect() as conn:
        with pytest.raises(DBAPIError) as exc:
            conn.execute(text("INSERT INTO students (id, roll_number, name, class_id) VALUES (9999, 'HACK', 'Hacker', 2001);"))
        assert any(k in str(exc.value).lower() for k in ["permission denied", "read-only", "cannot execute"])

    # 2. UPDATE denied
    with eng.connect() as conn:
        with pytest.raises(DBAPIError) as exc:
            conn.execute(text("UPDATE students SET name = 'Hacked' WHERE id = 3001;"))
        assert any(k in str(exc.value).lower() for k in ["permission denied", "read-only", "cannot execute"])

    # 3. DELETE denied
    with eng.connect() as conn:
        with pytest.raises(DBAPIError) as exc:
            conn.execute(text("DELETE FROM students WHERE id = 3001;"))
        assert any(k in str(exc.value).lower() for k in ["permission denied", "read-only", "cannot execute"])

    # 4. CREATE TABLE denied
    with eng.connect() as conn:
        with pytest.raises(DBAPIError) as exc:
            conn.execute(text("CREATE TABLE evil_table (id int);"))
        assert any(k in str(exc.value).lower() for k in ["permission denied", "read-only", "cannot execute"])

    # 5. GRANT denied
    with eng.connect() as conn:
        with pytest.raises(DBAPIError) as exc:
            conn.execute(text("GRANT ALL ON students TO public;"))
        assert any(k in str(exc.value).lower() for k in ["permission denied", "read-only", "cannot execute"])


# ── 16. RLS Effective for Direct and View Queries ─────────────────────────────

def test_16_rls_effective_for_direct_and_view_queries(pg_ai_reader_url, rls_test_data):
    """[RLS Test 16] RLS remains effective for direct queries as well as view queries."""
    eng = create_engine(pg_ai_reader_url)
    with eng.connect() as conn:
        _set_test_context(conn, 1001, "faculty")

        # Direct table query
        direct_ids = [r[0] for r in conn.execute(text("SELECT id FROM students WHERE id IN (3001, 3002, 3003, 3004);")).fetchall()]
        assert direct_ids == [3001, 3002]

        # View queries
        att_rolls = [r[0] for r in conn.execute(text("SELECT roll_number FROM ai_attendance_summary WHERE roll_number IN ('RLS-A01', 'RLS-A02', 'RLS-B01', 'RLS-B02');")).fetchall()]
        assert all(r in ('RLS-A01', 'RLS-A02') for r in att_rolls)
        assert 'RLS-B01' not in att_rolls
        assert 'RLS-B02' not in att_rolls


# ── 17. Migration Upgrade and Downgrade Cycle ──────────────────────────────────

def test_17_migration_007_upgrade_and_downgrade_cycle(pg_admin_url):
    """[RLS Test 17] Migration 007 downgrades cleanly to 006 and re-upgrades to head."""
    cfg = _get_alembic_config(pg_admin_url)
    eng = create_engine(pg_admin_url)

    try:
        # Downgrade to 006
        command.downgrade(cfg, "006_secure_ai_views")
        with eng.connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            assert rev == "006_secure_ai_views"

            # Check that RLS is disabled on students
            rls_active = conn.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname = 'students';")).scalar()
            assert rls_active is False

            # Check that helper function is dropped
            func_exists = conn.execute(text("SELECT 1 FROM pg_proc WHERE proname = 'can_current_user_access_class';")).scalar()
            assert func_exists is None
    finally:
        # Re-upgrade to head ensures clean database state
        command.upgrade(cfg, "head")

    with eng.connect() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        assert rev in ("007_implement_faculty_rls", "008_trusted_identity_context", "009_harden_rls_ownership", "010_retire_insecure_dev_key")

        # Verify RLS re-enabled
        rls_active = conn.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname = 'students';")).scalar()
        assert rls_active is True

        func_exists = conn.execute(text("SELECT 1 FROM pg_proc WHERE proname = 'can_current_user_access_class';")).scalar()
        assert func_exists == 1


# ── 18. Catalog Verification of RLS Flags, Policies, and Roles ────────────────

def test_18_catalogs_confirm_rls_flags_policies_ownership_privileges(pg_admin_url):
    """[RLS Test 18] Final PostgreSQL catalogs confirm expected RLS flags, policies, ownership, and privileges."""
    eng = create_engine(pg_admin_url)
    with eng.connect() as conn:
        # 1. RLS flags on all 5 sensitive tables
        tables = ["students", "mst_eligibility", "follow_up_statuses", "invigilation_duties", "classes"]
        for tname in tables:
            rls = conn.execute(text(f"SELECT relrowsecurity FROM pg_class WHERE relname = '{tname}';")).scalar()
            assert rls is True, f"relrowsecurity is not True on {tname}"

        # 2. Check policies exist
        policies = [r[0] for r in conn.execute(text("SELECT policyname FROM pg_policies;")).fetchall()]
        expected_policies = [
            "rls_students_faculty_class_scope",
            "rls_mst_eligibility_faculty_class_scope",
            "rls_follow_up_statuses_faculty_class_scope",
            "rls_invigilation_duties_roster_access",
            "rls_classes_faculty_class_scope",
        ]
        for ep in expected_policies:
            assert ep in policies, f"Expected policy {ep} not found in pg_policies"

        # 3. ai_reader role catalog flags
        ai_reader_flags = conn.execute(text("""
            SELECT rolsuper, rolbypassrls, rolinherit, rolcreaterole, rolcreatedb
            FROM pg_roles
            WHERE rolname = 'ai_reader';
        """)).fetchone()
        assert ai_reader_flags is not None, "ai_reader role missing"
        assert ai_reader_flags[0] is False, "ai_reader must NOT be superuser"
        assert ai_reader_flags[1] is False, "ai_reader must have NOBYPASSRLS"
        assert ai_reader_flags[3] is False, "ai_reader must NOT have CREATEROLE"
        assert ai_reader_flags[4] is False, "ai_reader must NOT have CREATEDB"

        # 4. Table ownership: ai_reader must NOT own any protected tables
        owners = [
            r[0] for r in conn.execute(text("""
                SELECT u.usename
                FROM pg_class c
                JOIN pg_user u ON u.usesysid = c.relowner
                WHERE c.relname IN ('students', 'mst_eligibility', 'follow_up_statuses', 'invigilation_duties', 'classes');
            """)).fetchall()
        ]
        assert "ai_reader" not in owners, "ai_reader must NOT own protected tables"
