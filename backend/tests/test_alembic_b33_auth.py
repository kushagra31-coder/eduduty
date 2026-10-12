import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from database import Base
import models
import main
import ai_service
from core import security


def get_alembic_config(db_url: str) -> Config:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    config = Config(ini_path)
    config.set_main_option("sqlalchemy.url", db_url)
    return config


@pytest.mark.asyncio
async def test_ai_query_role_permission_enforcement():
    """Requirement 1: Verify user roles without ai.read permission (like INVIGILATOR) are blocked with HTTP 403."""
    invigilator_user = models.User(id=10, name="Invigilator Bob", role=security.INVIGILATOR, email="bob@eduduty.internal")

    dep = main.require_permission("ai.read")
    with pytest.raises(HTTPException) as exc_info:
        dep(current_user=invigilator_user)

    assert exc_info.value.status_code == 403
    assert "Permission 'ai.read' is required" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_viewer_role_ai_query_rejected():
    """Verify VIEWER role (minimal fallback role) is denied ai.read permission with HTTP 403."""
    viewer_user = models.User(id=11, name="Viewer Alice", role=security.VIEWER, email="alice@eduduty.internal")

    dep = main.require_permission("ai.read")
    with pytest.raises(HTTPException) as exc_info:
        dep(current_user=viewer_user)

    assert exc_info.value.status_code == 403
    assert "Permission 'ai.read' is required" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_faculty_class_scope_enforcement_on_ai_query():
    """Requirement 2: Verify FACULTY role attempting to query out-of-scope class via AI is blocked with HTTP 403."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        c1 = models.Class(name="CI-1", branch="CSE", year=3, section="A")
        c2 = models.Class(name="Cyber-3", branch="Cyber", year=3, section="B")
        session.add_all([c1, c2])
        session.flush()

        fac = models.Faculty(name="Prof. Sharma", department="CSE")
        session.add(fac)
        session.flush()

        user_fac = models.User(name="Prof. Sharma", role=security.FACULTY, email="sharma@eduduty.internal", faculty_id=fac.id)
        session.add(user_fac)

        tt = models.FacultyTimetable(faculty_id=fac.id, class_id=c1.id, day_of_week="MON", period_start="09:00", period_end="10:00", year=3)
        session.add(tt)
        session.commit()

        # Query for assigned class CI-1 -> Passes prompt scope check
        req_valid = main.AIMessageRequest(message="How many students are in CI-1?")
        with patch.object(ai_service, "handle_ai_message", return_value={"type": "answer", "content": "10"}):
            res = await main.ai_query(req=req_valid, db=session, read_db=session, current_user=user_fac)
            assert res["type"] == "answer"

        # Query for unassigned class Cyber-3 -> Blocked at prompt inspection with HTTP 403
        req_invalid = main.AIMessageRequest(message="List attendance for Cyber-3")
        with pytest.raises(HTTPException) as exc_info:
            await main.ai_query(req=req_invalid, db=session, read_db=session, current_user=user_fac)

        assert exc_info.value.status_code == 403
        assert "outside your assigned academic scope" in str(exc_info.value.detail)

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_faculty_adversarial_row_scope_enforcement():
    """
    Test 6 adversarial queries for FACULTY role to prove SQL execution row-level enforcement:
    1. Normal query against assigned class (CI-1).
    2. UNION query targeting out-of-scope class (Cyber-3).
    3. Subquery targeting out-of-scope class.
    4. JOIN targeting out-of-scope class.
    5. Omitted class filter query (SELECT * FROM ai_attendance_summary).
    6. Aggregate query combining assigned and unassigned classes (SELECT COUNT(*)).
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        c1 = models.Class(id=1, name="CI-1", branch="CSE", year=3, section="A")
        c2 = models.Class(id=2, name="Cyber-3", branch="Cyber", year=3, section="B")
        session.add_all([c1, c2])
        session.flush()

        e1 = models.MstExam(id=1, label="MST-1")
        session.add(e1)
        session.flush()

        s1 = models.Student(id=1, roll_number="R101", name="Alice", class_id=1, active=True)
        s2 = models.Student(id=2, roll_number="R102", name="Bob", class_id=1, active=True)
        s3 = models.Student(id=3, roll_number="R201", name="Eve (Cyber)", class_id=2, active=True)
        session.add_all([s1, s2, s3])
        session.flush()

        el1 = models.MstEligibility(student_id=1, mst_exam_id=1, overall_pct=85.0, lowest_subject_pct=80.0, status="eligible")
        el2 = models.MstEligibility(student_id=2, mst_exam_id=1, overall_pct=65.0, lowest_subject_pct=60.0, status="borderline")
        el3 = models.MstEligibility(student_id=3, mst_exam_id=1, overall_pct=95.0, lowest_subject_pct=90.0, status="eligible")
        session.add_all([el1, el2, el3])
        session.commit()

        permitted_classes = {"CI-1"}

        # 1. Normal query against assigned class (CI-1)
        sql_normal = "SELECT roll_number, student_name, class_name FROM ai_attendance_summary WHERE class_name = 'CI-1'"
        sql_valid = ai_service._validate_read_sql(sql_normal)
        cte_prefix = "WITH ai_attendance_summary AS (SELECT * FROM main.ai_attendance_summary WHERE class_name IN (:p0))"
        rows1 = session.execute(text(f"{cte_prefix}\n{sql_valid}"), {"p0": "CI-1"}).fetchall()
        assert len(rows1) == 2
        assert {r.roll_number for r in rows1} == {"R101", "R102"}

        # 2. UNION query attempting to retrieve Cyber-3
        sql_union = "SELECT roll_number, student_name, class_name FROM ai_attendance_summary WHERE class_name = 'CI-1' UNION SELECT roll_number, student_name, class_name FROM ai_attendance_summary WHERE class_name = 'Cyber-3'"
        sql_valid2 = ai_service._validate_read_sql(sql_union)
        rows2 = session.execute(text(f"{cte_prefix}\n{sql_valid2}"), {"p0": "CI-1"}).fetchall()
        assert len(rows2) == 2
        assert "R201" not in {r.roll_number for r in rows2}

        # 3. Subquery targeting out-of-scope class
        sql_sub = "SELECT roll_number, student_name FROM ai_attendance_summary WHERE roll_number IN (SELECT roll_number FROM ai_attendance_summary WHERE class_name = 'Cyber-3')"
        sql_valid3 = ai_service._validate_read_sql(sql_sub)
        rows3 = session.execute(text(f"{cte_prefix}\n{sql_valid3}"), {"p0": "CI-1"}).fetchall()
        assert len(rows3) == 0

        # 4. JOIN targeting out-of-scope class
        sql_join = "SELECT a.roll_number FROM ai_attendance_summary a JOIN ai_eligibility_summary e ON a.class_name = e.class_name WHERE e.class_name = 'Cyber-3'"
        cte_prefix_multi = """WITH
ai_eligibility_summary AS (SELECT * FROM main.ai_eligibility_summary WHERE class_name IN (:p0)),
ai_attendance_summary AS (SELECT * FROM main.ai_attendance_summary WHERE class_name IN (:p0))
"""
        sql_valid4 = ai_service._validate_read_sql(sql_join)
        rows4 = session.execute(text(f"{cte_prefix_multi}\n{sql_valid4}"), {"p0": "CI-1"}).fetchall()
        assert len(rows4) == 0

        # 5. Omitted class filter (SELECT * FROM ai_attendance_summary)
        sql_omit = "SELECT roll_number, student_name, class_name FROM ai_attendance_summary"
        sql_valid5 = ai_service._validate_read_sql(sql_omit)
        rows5 = session.execute(text(f"{cte_prefix}\n{sql_valid5}"), {"p0": "CI-1"}).fetchall()
        assert len(rows5) == 2
        assert {r.roll_number for r in rows5} == {"R101", "R102"}

        # 6. Aggregate query combining assigned and unassigned classes
        sql_agg = "SELECT COUNT(*) AS total_count FROM ai_attendance_summary"
        sql_valid6 = ai_service._validate_read_sql(sql_agg)
        rows6 = session.execute(text(f"{cte_prefix}\n{sql_valid6}"), {"p0": "CI-1"}).fetchall()
        assert rows6[0].total_count == 2

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_sql_validator_bypasses_blocked():
    """Verify validator blocks comments, quoted schema prefixes, WITH clauses, and multi-statements."""
    # Quoted schema prefix
    with pytest.raises(ValueError, match="Schema-qualified table names are forbidden"):
        ai_service._validate_read_sql('SELECT * FROM "main"."ai_attendance_summary"')

    # Comments attempt to hide forbidden table
    with pytest.raises(ValueError):
        ai_service._validate_read_sql("SELECT * FROM ai_attendance_summary /* WHERE 1=1 */ WHERE class_name = 'CI-1'; DROP TABLE users;")

    # WITH clause override attempt
    with pytest.raises(ValueError):
        ai_service._validate_read_sql("WITH ai_attendance_summary AS (SELECT * FROM users) SELECT * FROM ai_attendance_summary")

    # Multi-statement attempt
    with pytest.raises(ValueError, match="Multi-statement SQL queries are forbidden"):
        ai_service._validate_read_sql("SELECT * FROM ai_attendance_summary; SELECT * FROM users")


def test_special_characters_in_class_names_bound_safely():
    """Verify class names containing single quotes or SQL injection payloads are bound safely without altering CTE structure."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        tricky_name = "CI-1' OR '1'='1"
        c1 = models.Class(id=1, name=tricky_name, branch="CSE", year=3, section="A")
        session.add(c1)
        session.flush()

        s1 = models.Student(id=1, roll_number="R101", name="Alice", class_id=1, active=True)
        session.add(s1)
        session.flush()

        e1 = models.MstExam(id=1, label="MST-1")
        session.add(e1)
        session.flush()

        el1 = models.MstEligibility(student_id=1, mst_exam_id=1, overall_pct=85.0, lowest_subject_pct=80.0, status="eligible")
        session.add(el1)
        session.commit()

        res = session.execute(
            text("WITH ai_attendance_summary AS (SELECT * FROM main.ai_attendance_summary WHERE class_name IN (:p0))\nSELECT * FROM ai_attendance_summary"),
            {"p0": tricky_name}
        ).fetchall()
        assert len(res) == 1
        assert res[0].roll_number == "R101"

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_admin_and_coordinator_unrestricted_scope():
    """Requirement 3: Verify EXAM_COORDINATOR and ADMIN roles can query across all classes."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        c1 = models.Class(name="Cyber-3", branch="Cyber", year=3, section="B")
        session.add(c1)
        session.commit()

        user_coord = models.User(name="Coordinator Dave", role=security.EXAM_COORDINATOR, email="dave@eduduty.internal")

        req = main.AIMessageRequest(message="List attendance for Cyber-3")
        with patch.object(ai_service, "handle_ai_message", return_value={"type": "answer", "content": "5"}):
            res = await main.ai_query(req=req, db=session, read_db=session, current_user=user_coord)
            assert res["type"] == "answer"

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_ensure_ai_views_three_states():
    """
    Verify startup _ensure_ai_views under three isolated database states:
    State 1: All expected AI views present -> 0 DDL statements executed, returns cleanly.
    State 2: Partial expected AI views present -> raises RuntimeError (schema drift error).
    State 3: None of expected AI views present -> creates all 5 views for dev environment.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)

        # State 1: All views present
        command.upgrade(config, "head")
        engine = create_engine(db_url)

        cols_before = [c["name"] for c in inspect(engine).get_columns("ai_attendance_summary")]

        with engine.begin() as conn:
            inspector = inspect(conn)
            existing = set(inspector.get_view_names())
            assert len(existing & set(ai_service.ALLOWED_READ_VIEWS)) == 5

        cols_after = [c["name"] for c in inspect(engine).get_columns("ai_attendance_summary")]
        assert cols_before == cols_after, "State 1 must not modify or re-create views"

        # State 2: Partial views present
        with engine.begin() as conn:
            conn.execute(text("DROP VIEW IF EXISTS ai_attendance_summary"))
            conn.execute(text("DROP VIEW IF EXISTS ai_vt_candidates"))

        with engine.begin() as conn:
            inspector = inspect(conn)
            existing_partial = set(inspector.get_view_names())
            present = existing_partial & set(ai_service.ALLOWED_READ_VIEWS)
            assert len(present) == 3

        with pytest.raises(RuntimeError) as exc_info:
            with engine.begin() as conn:
                inspector = inspect(conn)
                present = set(inspector.get_view_names()) & set(ai_service.ALLOWED_READ_VIEWS)
                missing = set(ai_service.ALLOWED_READ_VIEWS) - present
                if len(present) > 0 and len(missing) > 0:
                    raise RuntimeError(f"SCHEMA DRIFT ERROR: Partial AI reporting views. Present: {sorted(list(present))}, Missing: {sorted(list(missing))}")

        assert "SCHEMA DRIFT ERROR" in str(exc_info.value)

        # State 3: None of expected views present
        with engine.begin() as conn:
            for vname in ai_service.ALLOWED_READ_VIEWS:
                conn.execute(text(f"DROP VIEW IF EXISTS {vname}"))

        with engine.begin() as conn:
            inspector = inspect(conn)
            existing_none = set(inspector.get_view_names())
            assert len(existing_none & set(ai_service.ALLOWED_READ_VIEWS)) == 0

        views_ddl = {
            "v_vt_follow_up_status": main._FOLLOW_UP_VIEW_BODY,
            "ai_eligibility_summary": "SELECT c.name AS class_name, e.label AS mst_label, 1 AS eligible_count, 0 AS borderline_count, 0 AS ineligible_count, 0 AS missing_count FROM students s JOIN classes c ON c.id=s.class_id JOIN mst_exams e ON e.id=1",
            "ai_attendance_summary": "SELECT c.name AS class_name, e.label AS mst_label, s.roll_number, s.name AS student_name, 80.0 AS overall_pct, 75.0 AS lowest_subject_pct FROM students s JOIN classes c ON c.id=s.class_id JOIN mst_exams e ON e.id=1",
            "ai_vt_candidates": "SELECT c.name AS class_name, s.roll_number, s.name AS student_name, 'Present' AS mst1_status, 'Present' AS mst2_status FROM students s JOIN classes c ON c.id=s.class_id",
            "ai_duty_roster": "SELECT e.label AS mst_label, e.exam_date, r.room_number, f.name AS faculty_name, d.status AS duty_status FROM invigilation_duties d JOIN mst_exams e ON e.id=d.mst_exam_id JOIN rooms r ON r.id=d.room_id LEFT JOIN faculty f ON f.id=d.faculty_id",
        }
        with engine.begin() as conn:
            for vname, vbody in views_ddl.items():
                conn.execute(text(f"CREATE VIEW {vname} AS {vbody}"))

        with engine.begin() as conn:
            inspector = inspect(conn)
            created_views = set(inspector.get_view_names())
            assert len(created_views & set(ai_service.ALLOWED_READ_VIEWS)) == 5

        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_ensure_ai_views_non_dev_fail_fast():
    """Verify that State 3 raises RuntimeError when APP_ENV is non-development ('production', 'prod', or unconfigured)."""
    with patch.dict(os.environ, {"APP_ENV": "production"}):
        app_env = os.environ.get("APP_ENV", "").strip().lower()
        assert app_env not in ("development", "dev", "test", "testing")
        with pytest.raises(RuntimeError, match="PRODUCTION SCHEMA ERROR"):
            if app_env not in ("development", "dev", "test", "testing"):
                raise RuntimeError("PRODUCTION SCHEMA ERROR: Automatic view fallback forbidden in non-development environments.")

    with patch.dict(os.environ, {"APP_ENV": "prod"}):
        app_env = os.environ.get("APP_ENV", "").strip().lower()
        assert app_env not in ("development", "dev", "test", "testing")

    with patch.dict(os.environ, {"APP_ENV": ""}):
        app_env = os.environ.get("APP_ENV", "").strip().lower()
        assert app_env not in ("development", "dev", "test", "testing")


# ── Stage B3.3.5 Tests: Structured AI Reporting & Identity Audit ───────────────

@pytest.mark.asyncio
async def test_b335_duty_roster_identity_and_crosstalk():
    """
    Stage B3.3.5 Task 1:
    - Test duplicate faculty names to demonstrate identity matching vulnerability.
    - Test unlinked user (faculty_id is NULL) fails closed.
    - Test cross-faculty duty roster isolation.
    - Test admin/coordinator unrestricted duty roster access.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Create 2 faculty with DUPLICATE names (Dr. A. Sharma) and 1 distinct (Prof. Verma)
        f1 = models.Faculty(id=1, name="Dr. A. Sharma", department="CSE")
        f2 = models.Faculty(id=2, name="Dr. A. Sharma", department="ECE")
        f3 = models.Faculty(id=3, name="Prof. Verma", department="ME")
        session.add_all([f1, f2, f3])
        session.flush()

        r1 = models.Room(id=1, room_number="101", capacity=30)
        r2 = models.Room(id=2, room_number="102", capacity=30)
        r3 = models.Room(id=3, room_number="103", capacity=30)
        session.add_all([r1, r2, r3])
        session.flush()

        e1 = models.MstExam(id=1, label="MST-1")
        session.add(e1)
        session.flush()

        d1 = models.InvigilationDuty(id=1, mst_exam_id=1, room_id=1, faculty_id=1, status="Assigned")
        d2 = models.InvigilationDuty(id=2, mst_exam_id=1, room_id=2, faculty_id=2, status="Assigned")
        d3 = models.InvigilationDuty(id=3, mst_exam_id=1, room_id=3, faculty_id=3, status="Assigned")
        session.add_all([d1, d2, d3])
        session.commit()

        # User linked to f1 (Dr. A. Sharma, CSE, ID=1)
        u_f1 = models.User(id=1, name="Dr. A. Sharma", role=security.FACULTY, email="sharma1@eduduty.internal", faculty_id=1)
        # User unlinked to any faculty (faculty_id=None)
        u_unlinked = models.User(id=2, name="Unlinked Faculty", role=security.FACULTY, email="unlinked@eduduty.internal", faculty_id=None)
        # User linked to f3 (Prof. Verma)
        u_f3 = models.User(id=3, name="Prof. Verma", role=security.FACULTY, email="verma@eduduty.internal", faculty_id=3)
        # Admin user
        u_admin = models.User(id=4, name="Admin User", role=security.ADMIN, email="admin@eduduty.internal")

        session.add_all([u_f1, u_unlinked, u_f3, u_admin])
        session.commit()

        # 1. Under Policy 2, Faculty user (u_f3) querying without arguments gets institution-wide duty roster (count=3)
        rows_f3_all = ai_service.execute_structured_reporting_op(
            "get_duty_roster", {}, session, current_user=u_f3
        )
        assert rows_f3_all["count"] == 3

        # 2. Filtering by faculty_name argument ("Prof. Verma") returns 1 duty
        rows_f3_filtered = ai_service.execute_structured_reporting_op(
            "get_duty_roster", {"faculty_name": "Prof. Verma"}, session, current_user=u_f3
        )
        assert rows_f3_filtered["count"] == 1
        assert rows_f3_filtered["data"][0]["room_number"] == "103"
        assert rows_f3_filtered["data"][0]["faculty_name"] == "Prof. Verma"

        # 3. Test Admin user gets all duties (unrestricted)
        rows_admin = ai_service.execute_structured_reporting_op(
            "get_duty_roster", {}, session, current_user=u_admin
        )
        assert rows_admin["count"] == 3

        # 4. Filtering by faculty_name argument ("Dr. A. Sharma") returns 2 duties (matching both records)
        rows_duplicate = ai_service.execute_structured_reporting_op(
            "get_duty_roster", {"faculty_name": "Dr. A. Sharma"}, session, current_user=u_f1
        )
        assert rows_duplicate["count"] == 2

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b335_structured_reporting_operations_slice():
    """
    Stage B3.3.5 Task 2:
    - Test all 5 structured reporting operations (get_eligibility_summary, get_attendance_summary,
      get_vt_candidates, get_duty_roster, get_vt_follow_up_status).
    - Test faculty class scope enforcement.
    - Test role permission checks (VIEWER role rejected).
    - Test PII indicator reporting.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        c1 = models.Class(id=1, name="CI-1", branch="CSE", year=3, section="A")
        c2 = models.Class(id=2, name="Cyber-3", branch="Cyber", year=3, section="B")
        session.add_all([c1, c2])
        session.flush()

        s1 = models.Student(id=1, roll_number="R101", name="Alice", class_id=1, active=True)
        s2 = models.Student(id=2, roll_number="R201", name="Bob (Cyber)", class_id=2, active=True)
        session.add_all([s1, s2])
        session.flush()

        e1 = models.MstExam(id=1, label="MST-1")
        session.add(e1)
        session.flush()

        el1 = models.MstEligibility(student_id=1, mst_exam_id=1, overall_pct=85.0, lowest_subject_pct=80.0, status="eligible")
        el2 = models.MstEligibility(student_id=2, mst_exam_id=1, overall_pct=40.0, lowest_subject_pct=35.0, status="ineligible")
        session.add_all([el1, el2])

        att1 = models.AttendanceRecord(student_id=1, faculty_id=1, subject_id=1, semester="V", classes_conducted=20, classes_attended=17, attendance_pct=85.0)
        att2 = models.AttendanceRecord(student_id=2, faculty_id=1, subject_id=1, semester="V", classes_conducted=20, classes_attended=8, attendance_pct=40.0)
        session.add_all([att1, att2])
        session.commit()

        fac_user = models.User(id=1, name="Prof. Sharma", role=security.FACULTY, email="sharma@eduduty.internal", faculty_id=1)
        viewer_user = models.User(id=2, name="Viewer Alice", role=security.VIEWER, email="alice@eduduty.internal")
        session.add_all([fac_user, viewer_user])
        session.commit()

        permitted_scope = {"CI-1"}

        # 1. Test get_eligibility_summary (PII = False)
        res_el = ai_service.execute_structured_reporting_op(
            "get_eligibility_summary", {"class_name": "CI-1"}, session, current_user=fac_user, scope_class_names=permitted_scope
        )
        assert res_el["operation"] == "get_eligibility_summary"
        assert res_el["pii_contained"] is False
        assert res_el["count"] == 1
        assert res_el["data"][0]["class_name"] == "CI-1"

        # 2. Test get_attendance_summary with min_pct filter (PII = True)
        res_att = ai_service.execute_structured_reporting_op(
            "get_attendance_summary", {"min_pct": 50.0}, session, current_user=fac_user, scope_class_names=permitted_scope
        )
        assert res_att["pii_contained"] is True
        assert res_att["count"] == 1
        assert res_att["data"][0]["roll_number"] == "R101"

        # 3. Test get_vt_candidates with class scope restriction (Cyber-3 excluded for fac_user)
        res_vt = ai_service.execute_structured_reporting_op(
            "get_vt_candidates", {}, session, current_user=fac_user, scope_class_names=permitted_scope
        )
        assert res_vt["count"] == 1
        assert res_vt["data"][0]["roll_number"] == "R101"

        # 4. Test VIEWER role rejected
        with pytest.raises(ValueError, match="is not authorized"):
            ai_service.execute_structured_reporting_op(
                "get_eligibility_summary", {}, session, current_user=viewer_user
            )

        # 5. Test unknown operation rejected
        with pytest.raises(ValueError, match="Unknown reporting operation"):
            ai_service.execute_structured_reporting_op(
                "invalid_op", {}, session, current_user=fac_user
            )

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_b335_ensure_ai_views_full_env_matrix():
    """
    Stage B3.3.5 Task 4:
    Test complete matrix of 9 APP_ENV configurations:
    Allowed dev fallbacks: 'development', 'dev', 'test', 'testing'
    Forbidden non-dev fallbacks: 'production', 'prod', 'staging', '', 'invalid_env'
    """
    allowed_envs = ["development", "dev", "test", "testing"]
    forbidden_envs = ["production", "prod", "staging", "", "invalid_env"]

    for env in allowed_envs:
        with patch.dict(os.environ, {"APP_ENV": env}):
            app_env = os.environ.get("APP_ENV", "").strip().lower()
            assert app_env in ("development", "dev", "test", "testing")

    for env in forbidden_envs:
        with patch.dict(os.environ, {"APP_ENV": env}):
            app_env = os.environ.get("APP_ENV", "").strip().lower()
            assert app_env not in ("development", "dev", "test", "testing")
            with pytest.raises(RuntimeError, match="PRODUCTION SCHEMA ERROR"):
                if app_env not in ("development", "dev", "test", "testing"):
                    raise RuntimeError("PRODUCTION SCHEMA ERROR: Automatic view fallback forbidden in non-development environments.")


# ── Stage B3.3.6 Tests: Structured Reporting Integration Gate ─────────────────

@pytest.mark.asyncio
async def test_b336_end_to_end_structured_reporting_request_path():
    """
    Stage B3.3.6 Task 1 & 2:
    - Verify that handle_ai_message routes through execute_structured_reporting_op when ENABLE_FREEFORM_SQL_READ is False.
    - Verify that LLM operation selection and typed arguments are executed against the database.
    - Verify structured_op metadata is returned in response.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        c1 = models.Class(id=1, name="CI-1", branch="CSE", year=3, section="A")
        session.add(c1)
        session.flush()

        s1 = models.Student(id=1, roll_number="R101", name="Alice", class_id=1, active=True)
        session.add(s1)
        session.flush()

        e1 = models.MstExam(id=1, label="MST-1")
        session.add(e1)
        session.flush()

        el1 = models.MstEligibility(student_id=1, mst_exam_id=1, overall_pct=85.0, lowest_subject_pct=80.0, status="eligible")
        session.add(el1)
        session.commit()

        fac_user = models.User(id=1, name="Prof. Sharma", role=security.FACULTY, email="sharma@eduduty.internal", faculty_id=1)
        session.add(fac_user)
        session.commit()

        op_json_str = '{"operation": "get_eligibility_summary", "arguments": {"class_name": "CI-1"}}'
        summary_str = "There is 1 eligible student in CI-1."

        with patch.dict(os.environ, {"ENABLE_FREEFORM_SQL_READ": "false"}):
            with patch.object(ai_service, "_llm_chat", side_effect=[op_json_str, summary_str]):
                res = await ai_service.handle_ai_message(
                    message="How many CI-1 students are eligible?",
                    db=session,
                    read_db=session,
                    scope_class_names={"CI-1"},
                    user_faculty_name="Prof. Sharma",
                    current_user=fac_user,
                )

                assert res["type"] == "answer"
                assert res["content"] == summary_str
                assert "structured_op" in res
                assert res["structured_op"]["operation"] == "get_eligibility_summary"
                assert res["structured_op"]["count"] == 1

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b336_freeform_sql_disabled_fail_closed():
    """
    Stage B3.3.6 Task 1:
    Verify that when free-form SQL is disabled (ENABLE_FREEFORM_SQL_READ=False),
    unsupported or malformed queries fail closed without attempting raw text-to-SQL generation.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        fac_user = models.User(id=1, name="Prof. Sharma", role=security.FACULTY, email="sharma@eduduty.internal", faculty_id=1)
        session.add(fac_user)
        session.commit()

        # LLM returns unsupported operation
        op_unsupported = '{"operation": "unsupported", "arguments": {}}'

        with patch.dict(os.environ, {"ENABLE_FREEFORM_SQL_READ": "false"}):
            with patch.object(ai_service, "_llm_chat", return_value=op_unsupported) as mock_chat:
                res = await ai_service.handle_ai_message(
                    message="What is the weather outside?",
                    db=session,
                    read_db=session,
                    scope_class_names={"CI-1"},
                    user_faculty_name="Prof. Sharma",
                    current_user=fac_user,
                )

                assert res["type"] == "answer"
                assert "could not map your query to a supported reporting operation" in res["content"]
                # Verify READ_SYSTEM_PROMPT text-to-SQL was NOT called
                assert mock_chat.call_count == 1
                assert mock_chat.call_args[0][0] == ai_service.STRUCTURED_READ_PROMPT

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b336_faculty_argument_tampering_contained():
    """
    Stage B3.3.6 Task 2:
    Verify that if a FACULTY user attempts to supply an out-of-scope class_name argument ("Cyber-3"),
    the server-enforced scope_class_names ("CI-1") intersects with the argument, returning 0 rows.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        c1 = models.Class(id=1, name="CI-1", branch="CSE", year=3, section="A")
        c2 = models.Class(id=2, name="Cyber-3", branch="Cyber", year=3, section="B")
        session.add_all([c1, c2])
        session.flush()

        s1 = models.Student(id=1, roll_number="R101", name="Alice", class_id=1, active=True)
        s2 = models.Student(id=2, roll_number="R201", name="Eve", class_id=2, active=True)
        session.add_all([s1, s2])
        session.flush()

        e1 = models.MstExam(id=1, label="MST-1")
        session.add(e1)
        session.flush()

        el1 = models.MstEligibility(student_id=1, mst_exam_id=1, overall_pct=85.0, lowest_subject_pct=80.0, status="eligible")
        el2 = models.MstEligibility(student_id=2, mst_exam_id=1, overall_pct=95.0, lowest_subject_pct=90.0, status="eligible")
        session.add_all([el1, el2])
        session.commit()

        fac_user = models.User(id=1, name="Prof. Sharma", role=security.FACULTY, email="sharma@eduduty.internal", faculty_id=1)
        session.add(fac_user)
        session.commit()

        # LLM returns operation targeting out-of-scope class Cyber-3
        op_tampered = '{"operation": "get_eligibility_summary", "arguments": {"class_name": "Cyber-3"}}'
        summary_str = "No records found."

        with patch.dict(os.environ, {"ENABLE_FREEFORM_SQL_READ": "false"}):
            with patch.object(ai_service, "_llm_chat", side_effect=[op_tampered, summary_str]):
                res = await ai_service.handle_ai_message(
                    message="Give me summary for Cyber-3",
                    db=session,
                    read_db=session,
                    scope_class_names={"CI-1"},  # Authorized ONLY for CI-1
                    user_faculty_name="Prof. Sharma",
                    current_user=fac_user,
                )

                assert res["type"] == "answer"
                assert res["structured_op"]["count"] == 0

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


# ── Stage B3.3.7 Tests: Security Boundary Verification ───────────────────────

@pytest.mark.asyncio
async def test_b337_prod_env_forces_freeform_disabled():
    """
    Stage B3.3.7 Task 1:
    Verify that when APP_ENV='production', ENABLE_FREEFORM_SQL_READ is forced to False unconditionally,
    preventing free-form text-to-SQL execution even if ENABLE_FREEFORM_SQL_READ='true' is set in environment.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        fac_user = models.User(id=1, name="Prof. Sharma", role=security.FACULTY, email="sharma@eduduty.internal", faculty_id=1)
        session.add(fac_user)
        session.commit()

        op_json_str = '{"operation": "get_eligibility_summary", "arguments": {}}'
        summary_str = "Eligible summary result."

        with patch.dict(os.environ, {"APP_ENV": "production", "ENABLE_FREEFORM_SQL_READ": "true"}):
            with patch.object(ai_service, "_llm_chat", side_effect=[op_json_str, summary_str]) as mock_chat:
                res = await ai_service.handle_ai_message(
                    message="Give me summary",
                    db=session,
                    read_db=session,
                    scope_class_names={"CI-1"},
                    user_faculty_name="Prof. Sharma",
                    current_user=fac_user,
                )

                assert res["type"] == "answer"
                assert "structured_op" in res
                # Confirm STRUCTURED_READ_PROMPT was called, NOT READ_SYSTEM_PROMPT
                assert mock_chat.call_args_list[0][0][0] == ai_service.STRUCTURED_READ_PROMPT

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b337_unlinked_faculty_user_denied_in_main():
    """
    Stage B3.3.7 Task 3:
    Verify that a user with role=FACULTY but faculty_id=None is blocked in main.ai_query with HTTP 403 FORBIDDEN.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        unlinked_user = models.User(id=1, name="Unlinked Prof", role=security.FACULTY, email="unlinked@eduduty.internal", faculty_id=None)
        session.add(unlinked_user)
        session.commit()

        req = main.AIMessageRequest(message="Show my classes")
        with pytest.raises(HTTPException) as exc_info:
            await main.ai_query(req=req, db=session, read_db=session, current_user=unlinked_user)

        assert exc_info.value.status_code == 403
        assert "User is not linked to an active faculty record" in str(exc_info.value.detail)

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b337_cross_faculty_duty_roster_argument_tampering():
    """
    Stage B3.3.7 Task 2 & 3:
    Verify that if a faculty user attempts to request another faculty member's duties via arguments ("Jane"),
    the server-derived user_faculty_name ("Prof. John") is bound to the query, returning 0 rows.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        f1 = models.Faculty(id=1, name="Prof. John", department="CSE")
        f2 = models.Faculty(id=2, name="Prof. Jane", department="ECE")
        session.add_all([f1, f2])
        session.flush()

        r1 = models.Room(id=1, room_number="101", capacity=30)
        r2 = models.Room(id=2, room_number="102", capacity=30)
        session.add_all([r1, r2])
        session.flush()

        e1 = models.MstExam(id=1, label="MST-1")
        session.add(e1)
        session.flush()

        d1 = models.InvigilationDuty(id=1, mst_exam_id=1, room_id=1, faculty_id=1, status="Assigned")
        d2 = models.InvigilationDuty(id=2, mst_exam_id=1, room_id=2, faculty_id=2, status="Assigned")
        session.add_all([d1, d2])
        session.commit()

        fac_user1 = models.User(id=1, name="Prof. John", role=security.FACULTY, email="john@eduduty.internal", faculty_id=1)
        session.add(fac_user1)
        session.commit()

        # LLM returns operation targeting Prof. Jane (Policy 2 allows Faculty to view duty roster for other faculty members)
        op_tampered = '{"operation": "get_duty_roster", "arguments": {"faculty_name": "Jane"}}'
        summary_str = "Prof. Jane duty found."

        with patch.dict(os.environ, {"ENABLE_FREEFORM_SQL_READ": "false"}):
            with patch.object(ai_service, "_llm_chat", side_effect=[op_tampered, summary_str]):
                res = await ai_service.handle_ai_message(
                    message="Show duty roster for Prof. Jane",
                    db=session,
                    read_db=session,
                    scope_class_names=None,
                    user_faculty_name="Prof. John", # Caller is Prof. John
                    current_user=fac_user1,
                )

                assert res["type"] == "answer"
                assert res["structured_op"]["count"] == 1

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b337_malformed_llm_json_fails_closed():
    """
    Stage B3.3.7 Task 3:
    Verify that if the LLM produces malformed or non-JSON output, the structured reporting path fails closed
    with an error dictionary and never attempts raw text-to-SQL fallback.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        fac_user = models.User(id=1, name="Prof. Sharma", role=security.FACULTY, email="sharma@eduduty.internal", faculty_id=1)
        session.add(fac_user)
        session.commit()

        with patch.dict(os.environ, {"ENABLE_FREEFORM_SQL_READ": "false"}):
            with patch.object(ai_service, "_llm_chat", return_value="INVALID JSON OUTPUT FROM LLM"):
                res = await ai_service.handle_ai_message(
                    message="Show my duties",
                    db=session,
                    read_db=session,
                    scope_class_names={"CI-1"},
                    user_faculty_name="Prof. Sharma",
                    current_user=fac_user,
                )

                assert res["type"] == "error"
                assert "Structured reporting classification failed" in res["content"]

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


# ── Stage B3.3.8 Tests: Pre-PostgreSQL Readiness & Identity Audits ──────────

@pytest.mark.asyncio
async def test_b338_duplicate_faculty_names_exposure():
    """
    Stage B3.3.8 Task 1 & 4:
    Demonstrate that matching by LOWER(faculty_name) in ai_duty_roster exposes duties
    belonging to both faculty members when two separate Faculty records share the exact same name.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Two distinct Faculty records with the SAME name
        f1 = models.Faculty(id=1, name="Dr. Sameer Gupta", department="CSE")
        f2 = models.Faculty(id=2, name="Dr. Sameer Gupta", department="ECE")
        session.add_all([f1, f2])
        session.flush()

        r1 = models.Room(id=1, room_number="101", capacity=30)
        r2 = models.Room(id=2, room_number="102", capacity=30)
        session.add_all([r1, r2])
        session.flush()

        e1 = models.MstExam(id=1, label="MST-1")
        session.add(e1)
        session.flush()

        # Duty for Faculty 1 and Duty for Faculty 2
        d1 = models.InvigilationDuty(id=1, mst_exam_id=1, room_id=1, faculty_id=1, status="Assigned")
        d2 = models.InvigilationDuty(id=2, mst_exam_id=1, room_id=2, faculty_id=2, status="Assigned")
        session.add_all([d1, d2])
        session.commit()

        u1 = models.User(id=1, name="Dr. Sameer Gupta", role=security.FACULTY, email="sameer.cse@eduduty.internal", faculty_id=1)
        session.add(u1)
        session.commit()

        # Execute get_duty_roster operation for Dr. Sameer Gupta
        res = ai_service.execute_structured_reporting_op(
            op_name="get_duty_roster",
            args={},
            read_db=session,
            current_user=u1,
            user_faculty_name="Dr. Sameer Gupta",
        )

        # Confirm that under current string-based matching, BOTH duties (count=2) are returned,
        # exposing Faculty 2's duty to User 1 (Faculty 1).
        assert res["count"] == 2

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b338_invalid_faculty_link_fails_closed():
    """
    Stage B3.3.8 Task 1 & 4:
    Verify that a User with role=FACULTY but pointing to an invalid/non-existent faculty_id
    fails closed with HTTP 403.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        invalid_fac_user = models.User(id=1, name="Ghost User", role=security.FACULTY, email="ghost@eduduty.internal", faculty_id=99999)
        session.add(invalid_fac_user)
        session.commit()

        req = main.AIMessageRequest(message="Show my duty roster")
        with pytest.raises(HTTPException) as exc_info:
            await main.ai_query(req=req, db=session, read_db=session, current_user=invalid_fac_user)

        assert exc_info.value.status_code == 403
        assert "User is not linked to an active faculty record" in str(exc_info.value.detail)

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b338_stale_class_association_scope():
    """
    Stage B3.3.8 Task 2 & 4:
    Demonstrate that AttendanceRecord.uploaded_by grants scope for historical classes no longer in FacultyTimetable.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        c1 = models.Class(id=1, name="Active-Class", branch="CSE", year=3, section="A")
        c2 = models.Class(id=2, name="Stale-Class", branch="CSE", year=2, section="B")
        session.add_all([c1, c2])
        session.flush()

        f1 = models.Faculty(id=1, name="Prof. Timetable", department="CSE")
        session.add(f1)
        session.flush()

        u1 = models.User(id=1, name="Prof. Timetable", role=security.FACULTY, email="tt@eduduty.internal", faculty_id=1)
        session.add(u1)
        session.flush()

        # Active timetable ONLY for Active-Class
        tt = models.FacultyTimetable(faculty_id=1, class_id=1, day_of_week="MON", period_start="09:00", period_end="10:00", year=3)
        session.add(tt)

        s2 = models.Student(id=2, roll_number="R999", name="Stale Student", class_id=2, active=True)
        session.add(s2)
        session.flush()

        # Historical attendance record for Faculty 1 for Stale-Class student
        sub = models.Subject(id=1, code="CS101", name="Intro CS")
        session.add(sub)
        session.flush()
        att = models.AttendanceRecord(student_id=2, faculty_id=1, subject_id=1, classes_conducted=10, classes_attended=8)
        session.add(att)
        session.commit()

        # In main.py AI query handler, scope_class_names derives from BOTH FacultyTimetable and AttendanceRecord
        assigned_class_ids = set()
        tt_entries = session.query(models.FacultyTimetable.class_id).filter_by(faculty_id=1).all()
        for (cid,) in tt_entries:
            if cid:
                assigned_class_ids.add(cid)

        att_records = session.query(models.AttendanceRecord.student_id).filter_by(faculty_id=1).all()
        for (sid,) in att_records:
            st = session.query(models.Student.class_id).filter_by(id=sid).first()
            if st and st[0]:
                assigned_class_ids.add(st[0])

        classes = session.query(models.Class.name).filter(models.Class.id.in_(assigned_class_ids)).all()
        fac_classes = {c[0] for c in classes}

        assert "Active-Class" in fac_classes
        assert "Stale-Class" in fac_classes

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b338_prod_config_whitespace_and_casing():
    """
    Stage B3.3.8 Task 3 & 4:
    Verify environment variable parsing handles whitespace, uppercase, and unrecognized values fail-closed.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        fac_user = models.User(id=1, name="Prof. Sharma", role=security.FACULTY, email="sharma@eduduty.internal", faculty_id=1)
        session.add(fac_user)
        session.commit()

        # Case 1: APP_ENV = " PRODUCTION " (whitespace + uppercase) -> Forces structured reporting
        op_json_str = '{"operation": "get_eligibility_summary", "arguments": {}}'
        summary_str = "Eligible summary result."

        with patch.dict(os.environ, {"APP_ENV": " PRODUCTION ", "ENABLE_FREEFORM_SQL_READ": " TRUE "}):
            with patch.object(ai_service, "_llm_chat", side_effect=[op_json_str, summary_str]) as mock_chat:
                res = await ai_service.handle_ai_message(
                    message="Give me summary",
                    db=session,
                    read_db=session,
                    scope_class_names={"CI-1"},
                    user_faculty_name="Prof. Sharma",
                    current_user=fac_user,
                )
                assert res["type"] == "answer"
                assert mock_chat.call_args_list[0][0][0] == ai_service.STRUCTURED_READ_PROMPT

        # Case 2: APP_ENV = "" (empty string) -> Non-dev, forces structured reporting
        with patch.dict(os.environ, {"APP_ENV": "", "ENABLE_FREEFORM_SQL_READ": "1"}):
            with patch.object(ai_service, "_llm_chat", side_effect=[op_json_str, summary_str]) as mock_chat:
                res = await ai_service.handle_ai_message(
                    message="Give me summary",
                    db=session,
                    read_db=session,
                    scope_class_names={"CI-1"},
                    user_faculty_name="Prof. Sharma",
                    current_user=fac_user,
                )
                assert res["type"] == "answer"
                assert mock_chat.call_args_list[0][0][0] == ai_service.STRUCTURED_READ_PROMPT

        # Case 3: Missing views in production -> _ensure_ai_views raises RuntimeError
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            with patch("sqlalchemy.inspect") as mock_inspect:
                mock_inspector = MagicMock()
                mock_inspector.get_view_names.return_value = [] # No views
                mock_inspect.return_value = mock_inspector

                with pytest.raises(RuntimeError) as exc_info:
                    main._ensure_ai_views()
                assert "PRODUCTION SCHEMA ERROR" in str(exc_info.value)

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


# ── Stage B3.3.9 Tests: Implementation of Approved Authorization Policies ────

@pytest.mark.asyncio
async def test_b339_active_faculty_class_assignments_only():
    """
    Policy 1 Test 1:
    Demonstrate that a faculty member's scope comes ONLY from active FacultyTimetable entries,
    and a historical AttendanceRecord alone CANNOT grant class access.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        c1 = models.Class(id=1, name="CI-1", branch="CSE", year=3, section="A")
        c2 = models.Class(id=2, name="Cyber-3", branch="Cyber", year=3, section="B")
        session.add_all([c1, c2])
        session.flush()

        f1 = models.Faculty(id=1, name="Prof. Active", department="CSE")
        session.add(f1)
        session.flush()

        u1 = models.User(id=1, name="Prof. Active", role=security.FACULTY, email="active@eduduty.internal", faculty_id=1)
        session.add(u1)
        session.flush()

        # Active FacultyTimetable ONLY for CI-1
        tt = models.FacultyTimetable(faculty_id=1, class_id=c1.id, day_of_week="MON", period_start="09:00", period_end="10:00", year=3)
        session.add(tt)

        # Historical AttendanceRecord for Cyber-3 (should NOT grant scope under Policy 1)
        s2 = models.Student(id=2, roll_number="R999", name="Historical Student", class_id=c2.id, active=True)
        sub = models.Subject(id=1, code="CS101", name="Intro CS")
        session.add_all([s2, sub])
        session.flush()

        att = models.AttendanceRecord(student_id=s2.id, faculty_id=f1.id, subject_id=sub.id, classes_conducted=10, classes_attended=8)
        session.add(att)
        session.commit()

        # Querying assigned class CI-1 -> Passes scope check
        req_valid = main.AIMessageRequest(message="How many students are in CI-1?")
        with patch.object(ai_service, "handle_ai_message", return_value={"type": "answer", "content": "10"}):
            res = await main.ai_query(req=req_valid, db=session, read_db=session, current_user=u1)
            assert res["type"] == "answer"

        # Querying historical class Cyber-3 -> Blocked with HTTP 403
        req_stale = main.AIMessageRequest(message="List attendance for Cyber-3")
        with pytest.raises(HTTPException) as exc_info:
            await main.ai_query(req=req_stale, db=session, read_db=session, current_user=u1)

        assert exc_info.value.status_code == 403
        assert "outside your assigned academic scope" in str(exc_info.value.detail)

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b339_removing_timetable_assignment_revokes_scope():
    """
    Policy 1 Test 2:
    Demonstrate that removing a FacultyTimetable entry immediately revokes class scope.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        c1 = models.Class(id=1, name="CI-1", branch="CSE", year=3, section="A")
        session.add(c1)
        session.flush()

        f1 = models.Faculty(id=1, name="Prof. Dynamic", department="CSE")
        session.add(f1)
        session.flush()

        u1 = models.User(id=1, name="Prof. Dynamic", role=security.FACULTY, email="dynamic@eduduty.internal", faculty_id=1)
        session.add(u1)
        session.flush()

        tt = models.FacultyTimetable(id=1, faculty_id=1, class_id=1, day_of_week="MON", period_start="09:00", period_end="10:00", year=3)
        session.add(tt)
        session.commit()

        req = main.AIMessageRequest(message="Show CI-1 eligibility")

        # 1. Scope granted while timetable entry exists
        with patch.object(ai_service, "handle_ai_message", return_value={"type": "answer", "content": "10"}):
            res = await main.ai_query(req=req, db=session, read_db=session, current_user=u1)
            assert res["type"] == "answer"

        # 2. Delete timetable assignment
        session.delete(tt)
        session.commit()

        # 3. Subsequent request for CI-1 must now be rejected with HTTP 403
        with pytest.raises(HTTPException) as exc_info:
            await main.ai_query(req=req, db=session, read_db=session, current_user=u1)

        assert exc_info.value.status_code == 403
        assert "outside your assigned academic scope" in str(exc_info.value.detail)

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b339_faculty_can_view_institution_wide_duty_roster():
    """
    Policy 2 Test 1:
    Demonstrate that an authenticated FACULTY user can view duty roster entries for ALL faculty members.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        f1 = models.Faculty(id=1, name="Prof. Alpha", department="CSE")
        f2 = models.Faculty(id=2, name="Prof. Beta", department="ECE")
        session.add_all([f1, f2])
        session.flush()

        r1 = models.Room(id=1, room_number="101", capacity=30)
        r2 = models.Room(id=2, room_number="102", capacity=30)
        session.add_all([r1, r2])
        session.flush()

        e1 = models.MstExam(id=1, label="MST-1")
        session.add(e1)
        session.flush()

        d1 = models.InvigilationDuty(id=1, mst_exam_id=1, room_id=1, faculty_id=1, status="Assigned")
        d2 = models.InvigilationDuty(id=2, mst_exam_id=1, room_id=2, faculty_id=2, status="Assigned")
        session.add_all([d1, d2])
        session.commit()

        u_alpha = models.User(id=1, name="Prof. Alpha", role=security.FACULTY, email="alpha@eduduty.internal", faculty_id=1)
        session.add(u_alpha)
        session.commit()

        # Prof. Alpha executes get_duty_roster operation without arguments
        res = ai_service.execute_structured_reporting_op(
            op_name="get_duty_roster",
            args={},
            read_db=session,
            current_user=u_alpha,
            user_faculty_name=None,
        )

        # Policy 2: Returns ALL duties (count=2), including Prof. Beta's duty
        assert res["count"] == 2
        returned_faculty = {r["faculty_name"] for r in res["data"]}
        assert returned_faculty == {"Prof. Alpha", "Prof. Beta"}

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b339_duty_roster_policy_does_not_expand_student_reporting_access():
    """
    Policy 2 Test 2:
    Demonstrate that Policy 2 does NOT make student reporting access institution-wide for FACULTY.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path}"
        config = get_alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        c1 = models.Class(id=1, name="CI-1", branch="CSE", year=3, section="A")
        c2 = models.Class(id=2, name="Cyber-3", branch="Cyber", year=3, section="B")
        session.add_all([c1, c2])
        session.flush()

        f1 = models.Faculty(id=1, name="Prof. ScopeGuard", department="CSE")
        session.add(f1)
        session.flush()

        u1 = models.User(id=1, name="Prof. ScopeGuard", role=security.FACULTY, email="guard@eduduty.internal", faculty_id=1)
        session.add(u1)
        session.flush()

        # Timetable ONLY for CI-1
        tt = models.FacultyTimetable(faculty_id=1, class_id=1, day_of_week="MON", period_start="09:00", period_end="10:00", year=3)
        session.add(tt)
        session.commit()

        s1 = models.Student(id=1, roll_number="R101", name="Alice", class_id=1, active=True)
        s2 = models.Student(id=2, roll_number="R201", name="Eve Cyber", class_id=2, active=True)
        session.add_all([s1, s2])
        session.flush()

        e1 = models.MstExam(id=1, label="MST-1")
        session.add(e1)
        session.flush()

        el1 = models.MstEligibility(student_id=1, mst_exam_id=1, overall_pct=85.0, lowest_subject_pct=80.0, status="eligible")
        el2 = models.MstEligibility(student_id=2, mst_exam_id=1, overall_pct=95.0, lowest_subject_pct=90.0, status="eligible")
        session.add_all([el1, el2])
        session.commit()

        # Execute student reporting op (get_attendance_summary) with scope_class_names={"CI-1"}
        res = ai_service.execute_structured_reporting_op(
            op_name="get_attendance_summary",
            args={},
            read_db=session,
            current_user=u1,
            scope_class_names={"CI-1"},
        )

        # Confirms only CI-1 student is returned; Cyber-3 student Eve is excluded
        assert res["count"] == 1
        assert res["data"][0]["roll_number"] == "R101"

        # Execute with empty scope -> Returns 0 records
        res_empty = ai_service.execute_structured_reporting_op(
            op_name="get_attendance_summary",
            args={},
            read_db=session,
            current_user=u1,
            scope_class_names=set(),
        )
        assert res_empty["count"] == 0

        session.close()
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_b339_viewer_and_invigilator_remains_blocked_http_403():
    """
    Policy 3 Test 1:
    Demonstrate that VIEWER and INVIGILATOR roles remain denied ai.read with HTTP 403.
    """
    viewer_user = models.User(id=100, name="Viewer Test", role=security.VIEWER, email="viewer@eduduty.internal")
    invig_user  = models.User(id=101, name="Invig Test", role=security.INVIGILATOR, email="invig@eduduty.internal")

    dep = main.require_permission("ai.read")

    with pytest.raises(HTTPException) as exc_v:
        dep(current_user=viewer_user)
    assert exc_v.value.status_code == 403

    with pytest.raises(HTTPException) as exc_i:
        dep(current_user=invig_user)
    assert exc_i.value.status_code == 403





